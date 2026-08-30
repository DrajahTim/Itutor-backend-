from rest_framework import serializers

from .models import ChatMessage, CourseDocument


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "topic", "role", "content", "created_at"]


class AskQuestionSerializer(serializers.Serializer):
    # What the frontend sends when a student asks the chatbot something.
    question = serializers.CharField()
    topic = serializers.IntegerField(required=False, allow_null=True)


class CourseDocumentSerializer(serializers.ModelSerializer):
    # Handles both paths: admins typing raw_text directly, or anyone
    # (admin or student) uploading a real file that gets parsed into
    # raw_text automatically (see CourseDocumentViewSet.perform_create).
    # is_mine mirrors the same pattern used on TopicSerializer.
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = CourseDocument
        fields = [
            "id", "topic", "title", "source_type",
            "file", "raw_text", "owner", "is_mine", "created_at",
        ]
        # owner is always set server-side (see the view), never trusted
        # from client input. raw_text becomes optional at the serializer
        # level since it may be auto-populated from an uploaded file
        # instead of typed in directly.
        read_only_fields = ["owner"]
        extra_kwargs = {"raw_text": {"required": False}}

    def get_is_mine(self, obj):
        request = self.context.get("request")
        return bool(request and obj.owner_id == request.user.id)