"""Evidence retrieval only: no answer generation or decision extraction."""
from pathlib import Path

from athar.config import STORE_PATH
from athar.embeddings import OpenAIEmbedder
from athar.models import RetrievedEvidence
from athar.vector_store import LocalVectorStore


def retrieve_evidence(
    query: str, top_k: int = 5, *, store_path: Path = STORE_PATH,
    embedder: OpenAIEmbedder | None = None,
) -> list[RetrievedEvidence]:
    """Embed a bilingual question and return scored source chunks from the local index."""
    if not query.strip():
        raise ValueError("Query must not be blank")
    if top_k < 1:
        raise ValueError("top_k must be positive")
    if not Path(store_path).is_file():
        raise FileNotFoundError("No vector index found. Run python -m scripts.ingest first.")
    store = LocalVectorStore.load(store_path)
    embedder = embedder or OpenAIEmbedder(model=store.model)
    if embedder.model != store.model:
        raise ValueError("Query embedding model does not match the stored index")
    vector = embedder.embed([query])[0]
    return store.search(vector, top_k)
