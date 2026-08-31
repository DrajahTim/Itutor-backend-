from django.db import models
from rest_framework import generics, permissions, serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from learning.permissions import IsAdminOrReadOnly

from .document_parsing import UnsupportedFileType, extract_text_from_file
from .models import ChatMessage, CourseDocument
from .rag_service import get_chatbot_answer
from .serializers import (
    AskQuestionSerializer,
    ChatMessageSerializer,
    CourseDocumentSerializer,
)

# How many prior messages to replay to the LLM for conversational memory.
# 8 messages is roughly four back-and-forth exchanges — enough for "explain
# that again" to make sense, without sending an ever-growing transcript
# (and token bill) on every single question. Retrieved course material is
# also competing for the same context window.
CHAT_HISTORY_LIMIT = 8


class AskChatbotView(APIView):
    # POST /api/chatbot/ask/ — the main chatbot endpoint.

    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chatbot"  # matches the "chatbot": "10/minute" rate in settings

    def post(self, request):
        serializer = AskQuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        question = data["question"]
        topic_id = data.get("topic")

        # Load the recent conversation BEFORE saving the new question, so
        # the question isn't replayed as its own context. Without this the
        # tutor is stateless and follow-ups like "explain that again" have
        # nothing to refer back to.
        #
        # Scoped to this student + topic so switching topics starts a
        # fresh thread (matching how MyChatHistoryView segments chats).
        # A null topic_id means general chat, which keeps its own thread.
        #
        # We take the LAST few turns, then flip to chronological order:
        # the API needs oldest→newest, but the newest messages are the
        # ones worth keeping when trimming for the token budget.
        recent_messages = list(
            ChatMessage.objects.filter(
                student=request.user, topic_id=topic_id
            ).order_by("-created_at")[:CHAT_HISTORY_LIMIT]
        )
        history = list(reversed(recent_messages))

        # Save the student's question as a ChatMessage first, so the
        # conversation history is preserved even if the Groq call fails.
        ChatMessage.objects.create(
            student=request.user,
            topic_id=topic_id,
            role="user",
            content=question,
        )

        answer = get_chatbot_answer(question, topic_id=topic_id, history=history)

        assistant_message = ChatMessage.objects.create(
            student=request.user,
            topic_id=topic_id,
            role="assistant",
            content=answer,
        )

        return Response(ChatMessageSerializer(assistant_message).data, status=201)


class MyChatHistoryView(generics.ListAPIView):
    # GET /api/chatbot/history/?topic=<id> — a student's chat log,
    # optionally filtered to one topic.
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = ChatMessage.objects.filter(student=self.request.user)
        topic_id = self.request.query_params.get("topic")
        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        return queryset


class CourseDocumentViewSet(generics.ListCreateAPIView):
    # POST /api/chatbot/documents/ — anyone authenticated can upload:
    #   - Admins uploading create a CURATED document (owner=None),
    #     visible to every student.
    #   - Students uploading create a PRIVATE document (owner=self),
    #     visible only to them.
    # Saving triggers the chunk_and_embed_document signal automatically,
    # same as before — this view's only new job is parsing an uploaded
    # file into raw_text first, and deciding ownership.
    # GET /api/chatbot/documents/ — lists curated docs + the caller's own.
    serializer_class = CourseDocumentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = CourseDocument.objects.filter(
            models.Q(owner__isnull=True) | models.Q(owner=user)
        )
        topic_id = self.request.query_params.get("topic")
        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        return queryset

    def perform_create(self, serializer):
        uploaded_file = self.request.FILES.get("file")
        raw_text = serializer.validated_data.get("raw_text", "")

        if uploaded_file:
            try:
                raw_text = extract_text_from_file(uploaded_file)
            except UnsupportedFileType as e:
                # DRF turns a ValidationError raised here into a proper
                # 400 response with a clear message for the frontend.
                raise serializers.ValidationError({"file": str(e)})

        # Admins curate shared content (owner=None); everyone else's
        # upload is private to them.
        owner = None if self.request.user.role == "admin" else self.request.user

        serializer.save(owner=owner, raw_text=raw_text)