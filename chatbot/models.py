from django.conf import settings
from django.db import models
from pgvector.django import VectorField

from learning.models import Topic


def document_upload_path(instance, filename):
    # Organizes uploaded files as media/documents/<user_id>/<filename>,
    # so files are easy to browse/audit per user on disk.
    owner_id = instance.owner_id or "curated"
    return f"documents/{owner_id}/{filename}"


class CourseDocument(models.Model):
    # A source material (a lecture note, textbook excerpt, etc.) that
    # gets chunked and embedded so the chatbot can retrieve from it.
    SOURCE_TYPE_CHOICES = (
        ("lecture_notes", "Lecture Notes"),
        ("textbook", "Textbook"),
        ("other", "Other"),
    )

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES, default="lecture_notes")
    # None = an official document an admin curated for a topic, visible
    # to every student studying it. Set to a User = a document that
    # student personally uploaded, visible only to them.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    # The actual uploaded file (PDF/DOCX/etc). Optional — admins can
    # still type raw_text directly without uploading a file at all.
    file = models.FileField(upload_to=document_upload_path, null=True, blank=True)
    # Extracted text content, used for chunking/embedding. When a file
    # is uploaded, this gets populated automatically by the parsing
    # pipeline rather than typed in directly.
    raw_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class DocumentChunk(models.Model):
    # A document gets split into smaller chunks (e.g. paragraphs) because
    # embedding an entire document as one vector loses precision — we want
    # to retrieve the SPECIFIC paragraph relevant to a question, not the
    # whole document.
    document = models.ForeignKey(CourseDocument, on_delete=models.CASCADE, related_name="chunks")
    content = models.TextField()
    chunk_index = models.PositiveIntegerField()
    # all-MiniLM-L6-v2 (our chosen sentence-transformers model) outputs
    # 384-dimensional vectors — this MUST match the model's output size.
    embedding = VectorField(dimensions=384, null=True)

    class Meta:
        ordering = ["document", "chunk_index"]

    def __str__(self):
        return f"{self.document.title} - chunk {self.chunk_index}"


class ChatMessage(models.Model):
    ROLE_CHOICES = (
        ("user", "User"),
        ("assistant", "Assistant"),
    )

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages"
    )
    # Nullable — a student might ask a general question not tied to
    # any specific topic.
    topic = models.ForeignKey(
        Topic, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_messages"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.student.email} - {self.role}: {self.content[:50]}"
