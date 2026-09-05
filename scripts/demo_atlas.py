"""Run the synthetic Atlas story through Athar's actual APIs and local pipelines."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from openai import OpenAIError

from athar.action_updates import ActionLedger, ActionMatcher, process_updates, save_ledger
from athar.chunking import chunk_documents
from athar.config import PROJECT_ROOT
from athar.embeddings import OpenAIEmbedder
from athar.extraction import ExtractionError, MemoryExtractor
from athar.ingestion import load_document
from athar.memory_store import extract_memory, save_memory
from athar.models import Decision
from athar.open_loops import latest_action_state, open_loops
from athar.reranking import two_stage_search
from athar.timeline import decision_timeline
from athar.vector_store import LocalVectorStore

EXAMPLES_DIR = PROJECT_ROOT / "examples" / "project_atlas"
QUESTION = "Why did the team replace Falcon Systems?"


def run_demo(output_dir: Path, *, examples_dir: Path = EXAMPLES_DIR) -> bool:
    """Run five stages, saving real results; return whether fixture expectations held.

    Only the first two documents enter the initial index/memory. The later meeting
    is parsed now but withheld until the lifecycle step. Fixture checks never alter
    model output or inject expected decisions, actions, or updates.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    print("ATHAR AI — PROJECT ATLAS DEMO", flush=True)
    print("Synthetic example • live OpenAI calls • no generated answers\n", flush=True)
    print("[1/5] Ingesting bilingual project evidence...", flush=True)
    initial_pages = []
    for name in ("procurement_plan.md", "meeting_03_ar.md"):
        initial_pages.extend(load_document(examples_dir / name, source_root=examples_dir))
    later_pages = load_document(examples_dir / "meeting_07_ar.md", source_root=examples_dir)
    initial_chunks, later_chunks = chunk_documents(initial_pages), chunk_documents(later_pages)
    embedder = OpenAIEmbedder()
    vectors = embedder.embed([chunk.text for chunk in initial_chunks])
    index_path = output_dir / "vector_store.npz"
    LocalVectorStore(initial_chunks, vectors, model=embedder.model).save(index_path)
    print(f"Documents parsed: {len({p.document_id for p in [*initial_pages, *later_pages]})}")
    print(f"Initial chunks indexed: {len(initial_chunks)}; later chunks held for step 5: {len(later_chunks)}\n", flush=True)

    print("[2/5] Building organizational memory...", flush=True)
    memory = extract_memory(initial_chunks, MemoryExtractor())
    memory_path = output_dir / "organizational_memory.json"
    save_memory(memory, memory_path)
    print(f"Decisions: {len(memory.decisions)} | Actions: {len(memory.action_items)} | Risks: {len(memory.risks)}")
    print(f"Grounding rejections: {len(memory.rejected_items)}\n", flush=True)

    print("[3/5] Decision intelligence", flush=True)
    print(f"Question: {QUESTION}", flush=True)
    search = two_stage_search(QUESTION, store_path=index_path, memory_path=memory_path,
                             cache_path=output_dir / "memory_vectors.npz", embedder=embedder)
    (output_dir / "search.json").write_text(search.model_dump_json(indent=2)+"\n", encoding="utf-8")
    print(f"Reranking: {search.rerank_status}")
    top = next((row for row in search.results if isinstance(row.result.item, Decision)), None)
    if top is None:
        print("No decision returned; inspect search.json.")
    else:
        decision = top.result.item
        print(f"Top decision (overall rank {top.reranked_rank}, base rank {top.base_rank}): {decision.title}")
        print(f"Rationale: {decision.rationale or 'Unknown'}")
        for ref in decision.evidence_references:
            print(f"Evidence: {ref.source} | page={ref.page} | chunk={ref.chunk_id}")
            print(ref.excerpt)
    print(flush=True)

    print("[4/5] Decision timeline", flush=True)
    timeline = decision_timeline(memory.decisions, source_chunks=memory.source_chunks)
    for entry in timeline:
        print(f"{entry.date or 'Unknown date'} [{entry.date_status}] → {entry.title}")
    print("Chronology records the latest known events, not which decision is authoritative.\n", flush=True)

    print("[5/5] Open-loop intelligence", flush=True)
    before = ActionLedger.from_memory(memory)
    save_ledger(before, output_dir / "actions_before.json")
    unresolved = open_loops(before)
    print(f"Before later evidence — unresolved commitments: {len(unresolved)}")
    for item in unresolved:
        print(f"  {item.owner or 'Unknown owner'} | {item.state} | {item.action.description}")
        print(f"  Action ID: {item.action.id}")
    print("Processing the September 7 follow-up...", flush=True)
    report = process_updates(before, later_chunks, cache_path=output_dir / "action_vectors.npz",
                             embedder=embedder, matcher=ActionMatcher())
    save_ledger(report.ledger, output_dir / "action_updates.json")
    print(f"Updates accepted: {report.accepted}; rejected: {report.rejected}; no match: {report.no_match}")
    transitions = []
    for item in unresolved:
        after = latest_action_state(report.ledger, item.action.id)
        print(f"Same action ID: {item.action.id}")
        print(f"State: {item.state} → {after.state}")
        for event in after.history:
            print(f"  {event.date or 'Unknown date'} | {event.event_type} | applied={event.applied}")
            for ref in event.evidence_references:
                print(f"  Evidence: {ref.source} | {ref.excerpt}")
        transitions.append({"before": item.model_dump(mode="json"), "after": after.model_dump(mode="json")})
    print(f"After later evidence — unresolved commitments: {len(open_loops(report.ledger))}")
    # These assertions describe the example's expectations, not production matching rules.
    checks = {
        "replacement_decision_top1": bool(top and top.reranked_rank == 1 and any(
            ref.source == "meeting_03_ar.md" for ref in top.result.evidence_references)),
        "initial_and_replacement_dates": {"2026-08-12", "2026-09-03"}.issubset(
            {str(entry.date) for entry in timeline}),
        "ahmed_commitment_completed_same_id": any(
            t["before"]["owner"] == "أحمد" and t["after"]["state"] == "completed"
            and t["before"]["action"] == t["after"]["action"] for t in transitions),
    }
    (output_dir / "demo_report.json").write_text(json.dumps(
        {"question": QUESTION, "checks": checks, "transitions": transitions,
         "timeline": [entry.model_dump(mode="json") for entry in timeline]}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    passed = all(checks.values())
    print("\nDemo checks passed." if passed else "\nSome demo expectations were not met; inspect demo_report.json.", flush=True)
    for name, success in checks.items():
        print(f"  {'PASS' if success else 'REVIEW'}: {name}")
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, epilog="Requires OPENAI_API_KEY in the project .env or environment. Uses live, billable API requests.")
    parser.parse_args(argv)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Set OPENAI_API_KEY in the project .env before running the live demo.", file=sys.stderr)
        return 1
    runtime_root = PROJECT_ROOT / "data" / "processed"
    runtime_root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(tempfile.mkdtemp(prefix="atlas-demo-", dir=runtime_root))
    try:
        passed = run_demo(output_dir)
    except (OpenAIError, ExtractionError, OSError, ValueError, TypeError, KeyError):
        print("Demo failed. Check dependencies, example files, API access, and connectivity. "
              "Partial artifacts are retained; provider details are suppressed.", file=sys.stderr)
        return 1
    finally:
        print(f"Artifacts: {output_dir.relative_to(PROJECT_ROOT)}", flush=True)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
