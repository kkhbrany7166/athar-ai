"""HTTP/workspace contracts. Engine records retain their original schemas."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from athar.models import Risk
from athar.timeline import DecisionTimelineEntry


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectCreate(APIModel):
    name: str = Field(default="Untitled project", min_length=1, max_length=80)


class ProjectRequest(APIModel):
    project_id: UUID


class SearchRequest(ProjectRequest):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=8)


class Document(APIModel):
    id: UUID
    filename: str
    size: int
    status: Literal["uploaded", "processing", "ready", "failed"] = "uploaded"
    kind: Literal["document", "followup"] = "document"


class Project(APIModel):
    id: UUID
    name: str
    synthetic: bool = False
    status: Literal["empty", "uploaded", "processing", "ready", "failed"] = "empty"
    stage: str = "Add project documents to begin."
    error: str | None = None
    documents: list[Document] = Field(default_factory=list)
    snapshot_id: UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Health(APIModel):
    status: Literal["ok"] = "ok"
    ai_configured: bool


class DecisionResponse(APIModel):
    timeline: list[DecisionTimelineEntry]
    risks: list[Risk]
    rejected_records: int = 0
