from django.test import TestCase
import pytest
from django.urls import reverse

from .models import ChatMessage, CourseDocument, DocumentChunk
from .rag_service import build_prompt, retrieve_relevant_chunks


class FakeChunk:
    # Lightweight stand-in for a DocumentChunk — build_prompt only ever
    # touches .content, so a full model instance isn't needed here.
    def __init__(self, content):
        self.content = content


class TestBuildPrompt:
    # Pure function, no DB, no mocking needed — this is the piece that
    # enforces "answer only from context" / "admit when you don't know".
    def test_no_chunks_falls_back_to_general_knowledge_prompt(self):
        prompt = build_prompt("What is the capital of France?", [])
        assert "general knowledge" in prompt
        assert "capital of France" in prompt

    def test_with_chunks_restricts_to_context(self):
        chunks = [FakeChunk("Bubble Sort has O(n^2) worst-case complexity.")]
        prompt = build_prompt("What is Bubble Sort's complexity?", chunks)
        assert "ONLY the context" in prompt
        assert "Bubble Sort has O(n^2)" in prompt


@pytest.mark.django_db
class TestRetrieveRelevantChunks:
    def test_filters_out_chunks_below_relevance_threshold(self, topic, mocker):
        # Question embedding will be mocked to exactly match chunk_a's
        # embedding (distance 0) and be orthogonal to chunk_b's
        # (distance 1, well above the 0.7 threshold).
        document = CourseDocument.objects.create(
            topic=topic, title="Doc", raw_text="placeholder"
        )
        # Bypass the auto-chunking signal's real embedding call by
        # deleting whatever it created, then inserting controlled chunks.
        DocumentChunk.objects.filter(document=document).delete()

        vector_a = [1.0] + [0.0] * 383
        vector_b = [0.0, 1.0] + [0.0] * 382

        chunk_a = DocumentChunk.objects.create(
            document=document, content="relevant chunk", chunk_index=0, embedding=vector_a
        )
        DocumentChunk.objects.create(
            document=document, content="irrelevant chunk", chunk_index=1, embedding=vector_b
        )

        mocker.patch("chatbot.rag_service.generate_embedding", return_value=vector_a)

        results = retrieve_relevant_chunks("some question", topic_id=topic.id)

        assert len(results) == 1
        assert results[0].id == chunk_a.id

    def test_returns_empty_when_nothing_relevant(self, topic, mocker):
        document = CourseDocument.objects.create(topic=topic, title="Doc", raw_text="placeholder")
        DocumentChunk.objects.filter(document=document).delete()

        vector_a = [1.0] + [0.0] * 383
        vector_far = [0.0, 1.0] + [0.0] * 382

        DocumentChunk.objects.create(
            document=document, content="unrelated", chunk_index=0, embedding=vector_far
        )
        mocker.patch("chatbot.rag_service.generate_embedding", return_value=vector_a)

        results = retrieve_relevant_chunks("some question", topic_id=topic.id)
        assert results == []


@pytest.mark.django_db
class TestDocumentChunkingSignal:
    def test_creating_document_triggers_chunking(self, topic, mocker):
        mocker.patch("chatbot.signals.generate_embedding", return_value=[0.0] * 384)

        document = CourseDocument.objects.create(
            topic=topic,
            title="Test Doc",
            raw_text="First paragraph here.\n\nSecond paragraph here.",
        )

        chunks = DocumentChunk.objects.filter(document=document)
        assert chunks.count() == 2
        assert chunks.first().embedding is not None


@pytest.mark.django_db
class TestAskChatbotView:
    def test_requires_authentication(self, api_client):
        response = api_client.post(reverse("ask-chatbot"), {"question": "test"})
        assert response.status_code == 401

    def test_saves_both_user_and_assistant_messages(self, authenticated_client, student_user, mocker):
        # Mock at the view's import point — avoids any real embedding
        # model load or Groq API call during tests.
        mocker.patch(
            "chatbot.views.get_chatbot_answer",
            return_value="This is a mocked answer.",
        )

        response = authenticated_client.post(
            reverse("ask-chatbot"), {"question": "What is Bubble Sort?"}
        )

        assert response.status_code == 201
        assert response.data["role"] == "assistant"
        assert response.data["content"] == "This is a mocked answer."

        messages = ChatMessage.objects.filter(student=student_user).order_by("created_at")
        assert messages.count() == 2
        assert messages[0].role == "user"
        assert messages[0].content == "What is Bubble Sort?"
        assert messages[1].role == "assistant"
