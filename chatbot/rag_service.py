"""
Core RAG logic: given a student's question, find the most relevant
course material and ask an LLM (via Groq) to answer using that context.
"""
from decouple import config
from groq import Groq
from pgvector.django import CosineDistance

from .embedding_utils import generate_embedding
from .models import DocumentChunk

# Groq periodically decommissions hosted models, and when that happens
# every LLM call starts failing with a 404 "model_not_found" — which is
# exactly what killed quiz generation once llama-3.3-70b-versatile was
# retired. Reading it from the environment (with a working default) means
# the next retirement is a one-line .env change, not a code change.
# Must be a model that supports response_format={"type": "json_object"},
# since quiz generation depends on guaranteed-valid JSON.
GROQ_MODEL = config("GROQ_MODEL", default="openai/gpt-oss-120b")


# Cosine distance ranges from 0 (identical) to 2 (opposite). Anything
# above this threshold is treated as "not actually relevant" rather
# than force-feeding the LLM a weak match. 0.7 is a reasonably safe
# default for all-MiniLM-L6-v2 — tightened/loosened based on testing
# if real course content shows this cutting too aggressively either way.
RELEVANCE_THRESHOLD = 0.7


def retrieve_relevant_chunks(question: str, topic_id: int = None, top_k: int = 3):
    """
    Embeds the question, then finds the top_k most similar DocumentChunks
    using pgvector's cosine distance operator — but only keeps results
    that pass RELEVANCE_THRESHOLD. This prevents pgvector's "always
    return something" behavior from feeding the LLM irrelevant context
    just because it happened to be the closest of a bad set.
    """
    question_embedding = generate_embedding(question)

    queryset = DocumentChunk.objects.all()
    if topic_id:
        queryset = queryset.filter(document__topic_id=topic_id)

    results = (
        queryset
        .annotate(distance=CosineDistance("embedding", question_embedding))
        .order_by("distance")[:top_k]
    )

    # Filter out weak matches instead of trusting pgvector's top_k blindly.
    relevant = [r for r in results if r.distance <= RELEVANCE_THRESHOLD]
    return relevant


def build_system_prompt(chunks) -> str:
    """
    The tutor's standing instructions plus whatever course material was
    retrieved for this question.

    This is a *system* message rather than part of the user's turn so the
    conversation history can be replayed as real user/assistant turns
    after it — that's what gives the tutor memory of earlier messages.
    """
    if not chunks:
        return (
            "You are a helpful computer science tutor having an ongoing "
            "conversation with a student. No specific course material was "
            "found for their latest question, so answer from general "
            "knowledge, and mention that this isn't from their course "
            "materials specifically.\n\n"
            "Earlier messages in this conversation are provided for "
            "context — use them to resolve follow-up questions that refer "
            "back to what was already discussed."
        )

    context = "\n\n".join(chunk.content for chunk in chunks)
    return (
        "You are a helpful computer science tutor having an ongoing "
        "conversation with a student. Answer using ONLY the context "
        "below. If the context doesn't fully answer the question, say so "
        "honestly rather than making things up.\n\n"
        "Earlier messages in this conversation are provided for context — "
        "use them to resolve follow-up questions that refer back to what "
        "was already discussed.\n\n"
        f"Context:\n{context}"
    )


def get_chatbot_answer(question: str, topic_id: int = None, history=None) -> str:
    """
    `history` is an optional list of prior ChatMessage objects (oldest
    first) for this student and topic. Without it the tutor is
    stateless — every question looks like the first one, so follow-ups
    like "explain that again" have nothing to refer back to. Replaying
    the turns is what gives the conversation memory.
    """
    # Retrieval is still driven by the LATEST question — that's what the
    # student is actually asking about right now.
    chunks = retrieve_relevant_chunks(question, topic_id=topic_id)

    messages = [{"role": "system", "content": build_system_prompt(chunks)}]

    # ChatMessage.role is already "user"/"assistant", which is exactly
    # what the chat completions API expects — no mapping needed.
    for message in history or []:
        messages.append({"role": message.role, "content": message.content})

    messages.append({"role": "user", "content": question})

    client = Groq(api_key=config("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.3,
    )

    return response.choices[0].message.content


