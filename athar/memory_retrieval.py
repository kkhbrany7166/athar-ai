"""Hybrid ranking of structured organizational memory and raw document evidence."""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from athar.config import MAX_INPUT_BYTES, MEMORY_INDEX_PATH, MEMORY_PATH, STORE_PATH
from athar.embeddings import OpenAIEmbedder
from athar.memory_index import MemoryItem, cached_memory_vectors, memory_items, memory_search_text
from athar.memory_store import load_memory
from athar.models import ActionItem, Chunk, Decision, EvidenceReference, Record, Risk
from athar.timeline import DecisionTimelineEntry, decision_timeline
from athar.vector_store import LocalVectorStore, cosine_scores


class RankingConfig(Record):
    """Small uncalibrated prior for structured facts, gated by cosine relevance."""

    memory_bonus: float = Field(default=0.08, ge=0, le=0.25, allow_inf_nan=False)
    memory_min_cosine: float = Field(default=0.25, ge=-1, le=1, allow_inf_nan=False)


class SearchResult(Record):
    result_type: Literal["decision", "action_item", "risk", "document"]
    score: float = Field(allow_inf_nan=False)
    cosine_score: float = Field(ge=-1, le=1, allow_inf_nan=False)
    item_id: str | None
    sources: list[str] = Field(min_length=1)
    evidence_references: list[EvidenceReference] = Field(min_length=1)
    text: str
    item: Decision | ActionItem | Risk | None = None
    chunk: Chunk | None = None

    @model_validator(mode="after")
    def validate_domain(self) -> "SearchResult":
        expected = {"decision": Decision, "action_item": ActionItem, "risk": Risk}
        if self.result_type == "document":
            if self.chunk is None or self.item is not None or self.item_id is not None:
                raise ValueError("Document result must carry a chunk only")
        elif not isinstance(self.item, expected[self.result_type]) or self.item_id != self.item.id or self.chunk is not None:
            raise ValueError("Structured result must carry its matching memory object and ID")
        return self


class SearchResponse(Record):
    results: list[SearchResult]
    timeline: list[DecisionTimelineEntry]
    memory_available: bool
    ranking: RankingConfig


def rank_results(
    items: list[MemoryItem], memory_scores: list[float],
    chunks: list[Chunk], document_scores: list[float], *, top_k: int = 5,
    ranking: RankingConfig | None = None,
) -> list[SearchResult]:
    """Memory score = cosine + fixed bonus above the gate; document score = cosine.

    There is no per-domain min/max scaling, recency bonus, keyword rule, or forced
    domain quota. Low-scoring memory is excluded; raw evidence remains available.
    """
    ranking = ranking or RankingConfig()
    if top_k < 1 or len(items) != len(memory_scores) or len(chunks) != len(document_scores):
        raise ValueError("Invalid top_k or candidate score alignment")
    results = []
    for item, score in zip(items, memory_scores):
        if score < ranking.memory_min_cosine:
            continue
        kind = "decision" if isinstance(item, Decision) else "action_item" if isinstance(item, ActionItem) else "risk"
        results.append(SearchResult(
            result_type=kind, score=score + ranking.memory_bonus, cosine_score=score,
            item_id=item.id, sources=sorted({ref.source for ref in item.evidence_references}),
            evidence_references=item.evidence_references, text=memory_search_text(item), item=item,
        ))
    for chunk, score in zip(chunks, document_scores):
        # Raw result retains its full chunk and offsets; this short citation is a locator.
        excerpt = chunk.text.lstrip()[:600]
        results.append(SearchResult(
            result_type="document", score=score, cosine_score=score, item_id=None,
            sources=[chunk.source], text=chunk.text, chunk=chunk,
            evidence_references=[EvidenceReference(
                document_id=chunk.document_id, chunk_id=chunk.chunk_id,
                source=chunk.source, page=chunk.page, excerpt=excerpt,
            )],
        ))
    return sorted(results, key=lambda result: (-result.score, -result.cosine_score,
                  result.result_type, result.item_id or result.chunk.chunk_id))[:top_k]


def search_memory(
    query: str, top_k: int = 5, *, store_path: Path = STORE_PATH,
    memory_path: Path = MEMORY_PATH, cache_path: Path = MEMORY_INDEX_PATH,
    embedder: OpenAIEmbedder | None = None, ranking: RankingConfig | None = None,
) -> SearchResponse:
    """Search both domains with one query embedding and reuse unchanged memory vectors."""
    if not query.strip() or top_k < 1:
        raise ValueError("Query must be nonblank and top_k must be positive")
    if len(query.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("Query is too long for embedding")
    if Path(cache_path).resolve() in {Path(store_path).resolve(), Path(memory_path).resolve()}:
        raise ValueError("Memory cache path must differ from both input stores")
    raw = LocalVectorStore.load(store_path)
    embedder = embedder or OpenAIEmbedder(model=raw.model)
    if embedder.model != raw.model:
        raise ValueError("Embedding model must match the raw index")
    items = []
    available = Path(memory_path).is_file()
    if available:
        memory = load_memory(memory_path)
        raw_chunks = {chunk.chunk_id: chunk for chunk in raw.chunks}
        if any(raw_chunks.get(chunk.chunk_id) != chunk for chunk in memory.source_chunks):
            raise ValueError("Memory is stale relative to the raw index; run scripts.extract_memory again")
        items = memory_items(memory)
    vectors = cached_memory_vectors(items, embedder, cache_path, dimensions=raw.embeddings.shape[1])
    query_vector = embedder.embed([query])[0]
    memory_scores = cosine_scores(vectors, query_vector).tolist()
    document_scores = cosine_scores(raw.embeddings, query_vector).tolist()
    ranking = ranking or RankingConfig()
    results = rank_results(items, memory_scores, list(raw.chunks), document_scores,
                           top_k=top_k, ranking=ranking)
    timeline = decision_timeline(
        [result.item for result in results if isinstance(result.item, Decision)], source_chunks=raw.chunks,
    )
    return SearchResponse(results=results, timeline=timeline, memory_available=available, ranking=ranking)
