"""Source provenance, retrieval results, and organizational memory schemas."""
from datetime import date as Date
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    """Validate records strictly without discarding original evidence whitespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DocumentPage(Record):
    """One extracted page, or the entire text of a non-paginated source."""

    document_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    text: str


class SourceReference(Record):
    """Stable source identity; PDF page numbers are one-based."""

    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class EvidenceReference(SourceReference):
    """An exact, nonblank excerpt; application code verifies it against the chunk."""

    excerpt: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_excerpt(self) -> "EvidenceReference":
        if not self.excerpt.strip():
            raise ValueError("Evidence excerpt must not be blank")
        return self


class Chunk(SourceReference):
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
    """An evidence-backed organizational decision."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    rationale: str | None = None
    participants: list[str] = Field(default_factory=list)
    decision_date: Date | None = Field(default=None, validation_alias=AliasChoices("decision_date", "date"))
    decision_date_text: str | None = None
    evidence_references: list[EvidenceReference] = Field(min_length=1)


class ActionItem(Record):
    """A commitment with optional ownership and deadline."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str | None = None
    deadline: Date | None = None
    deadline_text: str | None = None
    status: Literal["unknown", "open", "in_progress", "done", "cancelled"] = "unknown"
    evidence_references: list[EvidenceReference] = Field(min_length=1)


class Risk(Record):
    """A risk with explicitly unknown defaults to avoid inventing facts."""

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["unknown", "low", "medium", "high", "critical"] = "unknown"
    status: Literal["unknown", "open", "mitigated", "closed"] = "unknown"
    evidence_references: list[EvidenceReference] = Field(min_length=1)
