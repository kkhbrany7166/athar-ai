"""An atomic local NumPy index with validated, co-located JSON metadata."""
import json
import os
from pathlib import Path
import tempfile
from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

from athar.models import Chunk, RetrievedEvidence


def normalize_vectors(embeddings: ArrayLike) -> NDArray[np.float32]:
    """Validate and normalize vector rows for either retrieval domain."""
    matrix = np.array(embeddings, dtype=np.float32, copy=True)
    if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
        raise ValueError("Embeddings must be a finite matrix with nonzero dimensions")
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1)
    if np.any(norms == 0):
        raise ValueError("Zero vectors cannot be searched with cosine similarity")
    normalized = (matrix / norms[:, None]).astype(np.float32)
    normalized.flags.writeable = False
    return normalized


def cosine_scores(normalized_vectors: NDArray[np.float32], query_embedding: ArrayLike) -> NDArray[np.float64]:
    """Score an already-normalized matrix against one finite, nonzero query."""
    query = np.asarray(query_embedding, dtype=np.float64)
    if query.shape != (normalized_vectors.shape[1],) or not np.isfinite(query).all():
        raise ValueError("Query embedding must be finite and match index dimensions")
    norm = np.linalg.norm(query)
    if norm == 0 or not np.isfinite(norm):
        raise ValueError("Query embedding must have a finite, nonzero norm")
    return np.clip(normalized_vectors @ (query / norm), -1.0, 1.0)


class LocalVectorStore:
    """Exact cosine search for a small corpus; all vectors are held in memory."""

    def __init__(self, chunks: Sequence[Chunk], embeddings: ArrayLike, *, model: str) -> None:
        matrix = np.array(embeddings, dtype=np.float32, copy=True)
        if matrix.ndim != 2 or matrix.shape[0] != len(chunks) or matrix.shape[1] == 0:
            raise ValueError("Embedding matrix must have one row per chunk and nonzero dimensions")
        if not chunks or not model:
            raise ValueError("Store requires chunks and an embedding model")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("Duplicate chunk IDs")
        self.embeddings = normalize_vectors(matrix)
        self.chunks = tuple(chunks)
        self.model = model

    def save(self, path: Path) -> None:
        """Replace one archive atomically so vectors and metadata cannot get out of sync."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = json.dumps({
            "version": 1, "model": self.model,
            "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
        }, ensure_ascii=False)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
                temporary = Path(stream.name)
                np.savez_compressed(stream, embeddings=self.embeddings, metadata=np.array(metadata))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> "LocalVectorStore":
        """Reload without pickle and validate the schema and row alignment."""
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            if metadata.get("version") != 1:
                raise ValueError("Unsupported vector-store version; rebuild the index")
            return cls(
                [Chunk.model_validate(item) for item in metadata["chunks"]],
                archive["embeddings"], model=metadata["model"],
            )

    def search(self, query_embedding: ArrayLike, top_k: int = 5) -> list[RetrievedEvidence]:
        """Return descending cosine scores; ties preserve original ingestion order."""
        if top_k < 1:
            raise ValueError("top_k must be positive")
        scores = cosine_scores(self.embeddings, query_embedding)
        indices = np.argsort(-scores, kind="stable")[:top_k]
        return [RetrievedEvidence(chunk=self.chunks[int(i)], score=float(scores[i])) for i in indices]
