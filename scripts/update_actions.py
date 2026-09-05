"""Match new documents to existing actions and atomically append verified updates."""
import argparse
from pathlib import Path
import sys

from openai import OpenAIError
from pypdf.errors import PyPdfError

from athar.action_updates import ActionLedger, ActionMatcher, load_ledger, process_updates, save_ledger
from athar.chunking import chunk_documents
from athar.config import ACTION_INDEX_PATH, ACTION_UPDATES_PATH, MEMORY_PATH
from athar.embeddings import OpenAIEmbedder
from athar.ingestion import load_documents
from athar.memory_store import load_memory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, required=True, help="Directory of new meeting/document material")
    parser.add_argument("--memory", type=Path, default=MEMORY_PATH)
    parser.add_argument("--updates", type=Path, default=ACTION_UPDATES_PATH)
    parser.add_argument("--cache", type=Path, default=ACTION_INDEX_PATH)
    args = parser.parse_args(argv)
    if len({p.resolve() for p in (args.memory, args.updates, args.cache)}) != 3:
        parser.error("Memory, update ledger, and cache paths must differ")
    try:
        memory = load_memory(args.memory)
        ledger = load_ledger(args.updates, memory)
        # Preserve historical snapshots while including newly extracted commitments.
        actions = {a.id: a for a in ledger.actions}
        chunks = {c.chunk_id: c for c in ledger.source_chunks}
        for action in memory.action_items:
            if action.id in actions and actions[action.id] != action:
                raise ValueError("Historical action identity was modified")
            actions[action.id] = action
        for chunk in memory.source_chunks:
            if chunk.chunk_id in chunks and chunks[chunk.chunk_id] != chunk:
                raise ValueError("Historical source identity was modified")
            chunks[chunk.chunk_id] = chunk
        ledger = ActionLedger(actions=list(actions.values()), source_chunks=list(chunks.values()),
                              updates=ledger.updates, processed_sources=ledger.processed_sources)
        report = process_updates(ledger, chunk_documents(load_documents(args.documents)),
            cache_path=args.cache, embedder=OpenAIEmbedder(), matcher=ActionMatcher())
        save_ledger(report.ledger, args.updates)
    except (OpenAIError, OSError, ValueError, TypeError, PyPdfError):
        print("Action update processing failed. Check inputs, model access, and API connectivity. "
              "Existing action history was left unchanged.", file=sys.stderr)
        return 1
    print(f"Chunks processed: {report.processed}; skipped: {report.skipped}")
    print(f"Updates accepted: {report.accepted}; rejected: {report.rejected}; no match: {report.no_match}")
    print(f"Matching model requests: {report.matching_calls}")
    print(f"Action history saved to: {args.updates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
