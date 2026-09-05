"""Deterministic action state derived from original commitments and verified events."""
from collections import defaultdict
from datetime import date as Date
from typing import Literal

from pydantic import Field

from athar.action_updates import ActionLedger, ActionUpdate, evidence, header_date
from athar.models import ActionItem, EvidenceReference, Record

ActionState = Literal["open", "in_progress", "blocked", "completed", "cancelled", "unknown"]


class ActionHistoryEntry(Record):
    event_id: str
    event_type: str
    date: Date | None
    description: str
    evidence_references: list[EvidenceReference]
    applied: bool


class CurrentAction(Record):
    action: ActionItem
    state: ActionState
    owner: str | None
    assignment_date: Date | None
    latest_known_date: Date | None
    unresolved: bool
    warnings: list[str] = Field(default_factory=list)
    history: list[ActionHistoryEntry]


def latest_action_state(ledger: ActionLedger, action_id: str) -> CurrentAction:
    """Dated events drive state; undated/earlier/ambiguous same-day events need review.

    Reassignment changes owner only. A later progress/blocked event can reopen a
    completed action if explicitly matched; there is no time-based status change.
    """
    ledger = ActionLedger.model_validate(ledger.model_dump())
    action = next((a for a in ledger.actions if a.id == action_id), None)
    if action is None:
        raise ValueError("Unknown action ID")
    chunks = {c.chunk_id: c for c in ledger.source_chunks}
    dates = {header_date(chunks[r.chunk_id])[0] for r in action.evidence_references} - {None}
    assignment_date = next(iter(dates)) if len(dates) == 1 else None
    assignment_refs = list(action.evidence_references)
    for ref in action.evidence_references:
        chunk = chunks[ref.chunk_id]
        parsed, phrase = header_date(chunk)
        if parsed == assignment_date and phrase and not any(phrase in r.excerpt for r in assignment_refs):
            assignment_refs.append(evidence(chunk, phrase))
    state = "completed" if action.status == "done" else action.status
    owner, latest = action.owner, assignment_date
    history = [ActionHistoryEntry(event_id=action.id, event_type="assignment", date=assignment_date,
                                  description=action.description, evidence_references=assignment_refs, applied=True)]
    warnings = []
    groups: dict[Date | None, list[ActionUpdate]] = defaultdict(list)
    for update in ledger.updates:
        if update.action_id == action_id:
            groups[update.observed_date].append(update)
    transitions = {"progress": "in_progress", "completed": "completed", "cancelled": "cancelled", "blocked": "blocked"}
    for day in sorted(groups, key=lambda d: (d is None, d or Date.max)):
        events = sorted(groups[day], key=lambda u: u.id)
        status_types = {u.update_type for u in events if u.update_type != "reassigned"}
        new_owners = {u.new_owner for u in events if u.update_type == "reassigned"}
        applicable = day is not None and (assignment_date is None or day > assignment_date)
        if not applicable:
            warnings.append("Undated or not demonstrably later update retained without changing state")
        ambiguous = len(status_types) > 1 or len(new_owners) > 1
        if applicable and ambiguous:
            state, latest = "unknown", day
            warnings.append("Different same-day outcomes cannot be ordered; state is unknown")
        for event in events:
            applied = applicable and not ambiguous
            if applied and event.update_type == "reassigned":
                if event.previous_owner is not None and owner is not None and event.previous_owner != owner:
                    applied = False
                    warnings.append("Reassignment previous owner does not match latest known owner")
                else:
                    owner = event.new_owner
                    latest = day
            elif applied:
                state, latest = transitions[event.update_type], day
            history.append(ActionHistoryEntry(event_id=event.id, event_type=event.update_type, date=day,
                description=event.description, evidence_references=event.evidence_references, applied=applied))
    return CurrentAction(action=action, state=state, owner=owner, assignment_date=assignment_date,
        latest_known_date=latest, unresolved=state not in {"completed", "cancelled"}, warnings=warnings, history=history)


def list_actions(ledger: ActionLedger, *, owner: str | None = None, state: ActionState | None = None,
                 unresolved_only: bool = False) -> list[CurrentAction]:
    """Exact owner filtering (no inferred aliases); unknown counts as unresolved for review."""
    results = [latest_action_state(ledger, action.id) for action in ledger.actions]
    return [item for item in results if (owner is None or item.owner == owner)
            and (state is None or item.state == state) and (not unresolved_only or item.unresolved)]


def open_loops(ledger: ActionLedger, *, owner: str | None = None) -> list[CurrentAction]:
    return list_actions(ledger, owner=owner, unresolved_only=True)
