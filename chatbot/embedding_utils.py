"""
Embedding generation for the RAG pipeline.

We load the sentence-transformers model ONCE at module import time (not
per-request) because loading it is slow (~1-2 seconds) — doing that on
every API call would make the chatbot painfully slow.
"""
from sentence_transformers import SentenceTransformer

# all-MiniLM-L6-v2: small, fast, free, runs locally (no API call needed
# for embeddings), outputs 384-dimensional vectors. Good default choice
# for a project at this scale.
_model = None


def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def generate_embedding(text: str) -> list[float]:
    model = get_embedding_model()
    # .tolist() converts the numpy array to a plain Python list, which
    # is what pgvector's Django field expects when saving.
    return model.encode(text).tolist()


def chunk_text(text: str, max_words: int = 150) -> list[str]:
    """
    Splits raw document text into smaller chunks for embedding.
    Simple strategy: split on paragraph breaks first, then further
    split any paragraph that's still too long. Good enough for an MVP —
    more sophisticated chunking (sentence-aware, overlapping windows)
    is a documented future improvement, not required for this scale.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []

    for para in paragraphs:
        words = para.split()
        if len(words) <= max_words:
            chunks.append(para)
        else:
            # Break oversized paragraphs into max_words-sized pieces.
            for i in range(0, len(words), max_words):
                chunks.append(" ".join(words[i:i + max_words]))

    return chunks