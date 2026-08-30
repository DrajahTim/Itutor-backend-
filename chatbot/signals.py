from django.db.models.signals import post_save
from django.dispatch import receiver

from .embedding_utils import chunk_text, generate_embedding
from .models import CourseDocument, DocumentChunk


@receiver(post_save, sender=CourseDocument)
def chunk_and_embed_document(sender, instance, created, **kwargs):
    # Fires automatically whenever a CourseDocument is created (e.g. an
    # admin adds course material via the admin panel or an API call).
    # Splits the raw text into chunks and generates an embedding for
    # each one immediately, so the chatbot can retrieve from it right
    # away without a separate manual step.
    if not created:
        return

    chunks = chunk_text(instance.raw_text)

    for index, chunk_content in enumerate(chunks):
        embedding = generate_embedding(chunk_content)
        DocumentChunk.objects.create(
            document=instance,
            content=chunk_content,
            chunk_index=index,
            embedding=embedding,
        )