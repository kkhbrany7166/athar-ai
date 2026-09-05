"""Batched OpenAI embeddings shared by Arabic, English, and mixed text."""
from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray
from openai import OpenAI

from athar.config import EMBEDDING_BATCH_SIZE, EMBEDDING_MODEL, MAX_BATCH_BYTES, MAX_INPUT_BYTES


class OpenAIEmbedder:
    """Lazily initialize the SDK so imports and CLI help never need credentials."""

    def __init__(self, *, model: str = EMBEDDING_MODEL, batch_size: int = EMBEDDING_BATCH_SIZE,
                 client: OpenAI | None = None) -> None:
        if not 1 <= batch_size <= 2048:
            raise ValueError("batch_size must be between 1 and 2048")
        self.model = model
        self.batch_size = batch_size
        self._client = client

    def embed(self, texts: Sequence[str]) -> NDArray[np.float32]:
        """Return vectors in input order; validate all texts before making requests."""
        if not texts:
            raise ValueError("At least one text is required")
        for text in texts:
            if not text.strip():
                raise ValueError("Embedding input must not be blank")
            if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
                raise ValueError(f"Embedding input exceeds {MAX_INPUT_BYTES} UTF-8 bytes; split it first")
        if self._client is None:
            self._client = OpenAI(timeout=60.0, max_retries=2)
        vectors = []
        start = 0
        while start < len(texts):
            end, byte_count = start, 0
            while end < len(texts) and end - start < self.batch_size:
                size = len(texts[end].encode("utf-8"))
                if byte_count + size > MAX_BATCH_BYTES:
                    break
                byte_count += size
                end += 1
            response = self._client.embeddings.create(
                model=self.model, input=list(texts[start:end]), encoding_format="float",
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if [item.index for item in ordered] != list(range(end - start)):
                raise ValueError("Embedding response indices do not match the requested batch")
            vectors.extend(item.embedding for item in ordered)
            start = end
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] == 0 or not np.isfinite(matrix).all():
            raise ValueError("Invalid embedding response")
        return matrix
