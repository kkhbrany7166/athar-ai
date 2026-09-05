"""Source provenance, retrieval results, and future organizational memory schemas."""
from datetime import date as Date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    """Validate records strictly without discarding original evidence whitespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentPage(Record):
    """One extracted page, or the entire text of a non-paginated source."""

    document_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    text: str


class EvidenceReference(Record):
    """Stable source identity; PDF page numbers are one-based."""

    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class Chunk(EvidenceReference):
    """Exact slice of extracted page text, using zero-based character offsets."""

    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self) -> "Chunk":
        if self.end_char - self.start_char != len(self.text):
            raise ValueError("Chunk offsets must match its text length")
        return self


class RetrievedEvidence(Record):
    """An evidence chunk and its cosine similarity (not a confidence score)."""

    chunk: Chunk
    score: float = Field(ge=-1, le=1, allow_inf_nan=False)


class Decision(Record):
    """Schema only: no automatic extraction is implemented."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rationale: str | None = None
    participants: list[str] = Field(default_factory=list)
    date: Date | None = None
    evidence_references: list[EvidenceReference] = Field(default_factory=list)


class ActionItem(Record):
    """A commitment with optional ownership and deadline."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str | None = None
    deadline: Date | None = None
    status: Literal["unknown", "open", "in_progress", "done", "cancelled"] = "unknown"
    evidence_references: list[EvidenceReference] = Field(default_factory=list)


class Risk(Record):
    """A risk with explicitly unknown defaults to avoid inventing facts."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["unknown", "low", "medium", "high", "critical"] = "unknown"
    status: Literal["unknown", "open", "mitigated", "closed"] = "unknown"
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
