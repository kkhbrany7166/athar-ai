"""Chronology of supplied decisions, without inferring supersession or correctness."""
from collections.abc import Iterable
from datetime import date
from typing import Literal

from pydantic import Field

from athar.extraction import parse_explicit_date
from athar.models import Chunk, Decision, EvidenceReference, Record


class DecisionTimelineEntry(Record):
    decision_id: str
    title: str
    description: str
    rationale: str | None
    date: date | None
    date_status: Literal["verified", "unknown", "unverified"]
    evidence_references: list[EvidenceReference] = Field(min_length=1)


def decision_timeline(
    decisions: Iterable[Decision], *, source_chunks: Iterable[Chunk],
) -> list[DecisionTimelineEntry]:
    """Order verified dates oldest first, with unknown/unverified dates last.

    Exact duplicate IDs are shown once. A date is usable only when its original
    phrase parses to the stored date and occurs in source-validated evidence.
    The caller supplies related decisions; this does not discover relationships.
    """
    chunks = {chunk.chunk_id: chunk for chunk in source_chunks}
    entries = []
    seen = set()
    for decision in decisions:
        if decision.id in seen:
            continue
        seen.add(decision.id)
        for reference in decision.evidence_references:
            chunk = chunks.get(reference.chunk_id)
            if chunk is None or (reference.document_id, reference.source, reference.page) != (
                chunk.document_id, chunk.source, chunk.page
            ) or reference.excerpt not in chunk.text:
                raise ValueError("Timeline evidence does not match supplied source chunks")
        phrase = decision.decision_date_text
        verified = (decision.decision_date is not None and phrase is not None
                    and parse_explicit_date(phrase) == decision.decision_date
                    and any(phrase in reference.excerpt for reference in decision.evidence_references))
        entries.append(DecisionTimelineEntry(
            decision_id=decision.id, title=decision.title, description=decision.description,
            rationale=decision.rationale, date=decision.decision_date if verified else None,
            date_status="verified" if verified else "unknown" if decision.decision_date is None else "unverified",
            evidence_references=decision.evidence_references,
        ))
    return sorted(entries, key=lambda entry: (entry.date is None, entry.date or date.max, entry.decision_id))
