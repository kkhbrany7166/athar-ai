"""Inspect unresolved commitments, owner/state filters, and evidence-backed action history."""
import argparse
from pathlib import Path
import sys

from athar.action_updates import load_ledger
from athar.config import ACTION_UPDATES_PATH, MEMORY_PATH
from athar.memory_store import load_memory
from athar.open_loops import latest_action_state, list_actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="Exact latest known owner name")
    parser.add_argument("--state", choices=["open", "in_progress", "blocked", "completed", "cancelled", "unknown"])
    parser.add_argument("--all", action="store_true", help="Include resolved actions")
    parser.add_argument("--history", metavar="ACTION_ID", help="Show original commitment and all update evidence")
    parser.add_argument("--memory", type=Path, default=MEMORY_PATH)
    parser.add_argument("--updates", type=Path, default=ACTION_UPDATES_PATH)
    args = parser.parse_args(argv)
    try:
        ledger = load_ledger(args.updates, load_memory(args.memory) if not args.updates.exists() else None)
        results = [latest_action_state(ledger, args.history)] if args.history else list_actions(
            ledger, owner=args.owner, state=args.state, unresolved_only=not args.all and args.state is None)
    except (OSError, ValueError, TypeError):
        print("Cannot load action history. Check the memory/ledger files and action ID.", file=sys.stderr)
        return 1
    for item in results:
        print(f"{item.state.upper()} | owner={item.owner or 'unknown'} | action_id={item.action.id}")
        print(item.action.description)
        print(f"Deadline: {item.action.deadline_text or item.action.deadline or 'unknown'}")
        for warning in item.warnings:
            print(f"Review: {warning}")
        if args.history:
            for event in item.history:
                print(f"{event.date or 'Unknown date'} | {event.event_type} | applied={event.applied}")
                print(event.description)
                for ref in event.evidence_references:
                    print(f"Evidence: {ref.source} | page={ref.page} | document={ref.document_id} | chunk={ref.chunk_id}")
                    print(ref.excerpt)
        else:
            for ref in item.action.evidence_references:
                print(f"Assignment evidence: {ref.source} | chunk={ref.chunk_id}")
        print()
    if not results:
        print("No matching actions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
