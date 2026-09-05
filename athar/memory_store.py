"""Transparent, atomically replaced JSON snapshots of verified organizational memory."""
from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
from typing import Literal

from pydantic import Field, model_validator

from athar.extraction import ChunkMemory, MemoryExtractor, PROMPT_VERSION
from athar.models import Chunk


class OrganizationalMemory(ChunkMemory):
    """Include the input chunks so citations remain independently inspectable."""

    schema_version: Literal[1] = 1
    extraction_model: str = Field(min_length=1)
    prompt_version: str = PROMPT_VERSION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_chunks: list[Chunk]

    @model_validator(mode="after")
    def validate_references(self) -> "OrganizationalMemory":
        chunks = {chunk.chunk_id: chunk for chunk in self.source_chunks}
        if len(chunks) != len(self.source_chunks):
            raise ValueError("Memory contains duplicate source chunk IDs")
        records = [*self.decisions, *self.action_items, *self.risks]
        if len({record.id for record in records}) != len(records):
            raise ValueError("Memory contains duplicate record IDs")
        for record in records:
            for reference in record.evidence_references:
                chunk = chunks.get(reference.chunk_id)
                if chunk is None or (
                    reference.document_id, reference.source, reference.page
                ) != (chunk.document_id, chunk.source, chunk.page) or reference.excerpt not in chunk.text:
                    raise ValueError("Memory evidence does not match its source chunk")
        if any(item.chunk_id not in chunks for item in self.rejected_items):
            raise ValueError("Rejection references an unknown source chunk")
        return self


def extract_memory(chunks: list[Chunk], extractor: MemoryExtractor) -> OrganizationalMemory:
    """Build a complete snapshot before any persistence; an API failure aborts the run."""
    results = [extractor.extract(chunk) for chunk in chunks]
    return OrganizationalMemory(
        extraction_model=extractor.model, source_chunks=chunks,
        decisions=[item for result in results for item in result.decisions],
        action_items=[item for result in results for item in result.action_items],
        risks=[item for result in results for item in result.risks],
        rejected_items=[item for result in results for item in result.rejected_items],
    )


def save_memory(memory: OrganizationalMemory, path: Path) -> None:
    """Validate again and atomically replace JSON; never write a partial run."""
    payload = OrganizationalMemory.model_validate(memory.model_dump()).model_dump_json(indent=2)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_memory(path: Path) -> OrganizationalMemory:
    """Reload and revalidate schema, source identities, and literal evidence excerpts."""
    return OrganizationalMemory.model_validate_json(Path(path).read_text(encoding="utf-8"))
