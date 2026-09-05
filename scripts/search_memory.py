"""Print ranked structured memory, raw evidence, and optional decision chronology."""
import argparse
from pathlib import Path
import sys
from zipfile import BadZipFile

from openai import OpenAIError

from athar.config import MEMORY_INDEX_PATH, MEMORY_PATH, STORE_PATH
from athar.memory_retrieval import RankingConfig
from athar.reranking import two_stage_search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Arabic, English, or mixed-language question")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--store", type=Path, default=STORE_PATH)
    parser.add_argument("--memory", type=Path, default=MEMORY_PATH)
    parser.add_argument("--cache", type=Path, default=MEMORY_INDEX_PATH)
    parser.add_argument("--timeline", action="store_true", help="Chronology of decisions in the returned results")
    parser.add_argument("--memory-bonus", type=float, default=0.08)
    parser.add_argument("--memory-min-cosine", type=float, default=0.25)
    parser.add_argument("--candidate-count", type=int, default=8, help="Top-N hybrid candidates, maximum 20")
    parser.add_argument("--no-rerank", action="store_true", help="Preserve baseline order without a reranking call")
    parser.add_argument("--json", action="store_true", help="Include complete base/reranked candidate ranks as JSON")
    args = parser.parse_args(argv)
    try:
        response = two_stage_search(args.query, args.top_k, candidate_count=args.candidate_count,
            enabled=not args.no_rerank, store_path=args.store,
            memory_path=args.memory, cache_path=args.cache,
            ranking=RankingConfig(memory_bonus=args.memory_bonus, memory_min_cosine=args.memory_min_cosine))
    except OpenAIError:
        print("Embedding request failed. Check API credentials, connectivity, and quota.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, BadZipFile):
        print("Search failed. Check arguments and index files; re-extract memory if its source index changed.", file=sys.stderr)
        return 1
    if args.json:
        print(response.model_dump_json(indent=2))
        return 0
    print(f"Reranking: {response.rerank_status} | model calls attempted: {response.rerank_model_calls}")
    if response.rerank_status == "fallback":
        print("Reranking unavailable or invalid; preserving hybrid order.")
    if not response.memory_available:
        print("No organizational memory file found; showing raw evidence only.")
    for row in response.results:
        result = row.result
        print(f"[{row.reranked_rank}] {result.result_type.upper()} | relevance={row.relevance} "
              f"| base_rank={row.base_rank} | base_score={row.base_score:.4f} | cosine={result.cosine_score:.4f}")
        if result.item_id:
            print(f"Item ID: {result.item_id}")
        print(result.text)
        for ref in result.evidence_references:
            page = f", page {ref.page}" if ref.page is not None else ""
            print(f"Evidence: {ref.source}{page} | document={ref.document_id} | chunk={ref.chunk_id}")
            if result.item_id:
                print(f"Excerpt: {ref.excerpt}")
        print()
    if args.timeline:
        print("Decision timeline (retrieved decisions only; chronological order does not establish correctness):")
        for entry in response.timeline:
            print(f"{entry.date or 'Unknown date'} [{entry.date_status}] | {entry.title} | id={entry.decision_id}")
        known = [entry for entry in response.timeline if entry.date is not None]
        if known:
            print(f"Latest known decision date among retrieved decisions: {known[-1].date}")
        elif not response.timeline:
            print("No decisions in the returned results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
