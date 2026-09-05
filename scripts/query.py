"""Print retrieved evidence and cosine scores without generating an answer."""
import argparse
from pathlib import Path
import sys
from zipfile import BadZipFile

from openai import OpenAIError

from athar.config import STORE_PATH
from athar.retrieval import retrieve_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Arabic, English, or mixed-language question")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--store", type=Path, default=STORE_PATH)
    args = parser.parse_args(argv)
    try:
        results = retrieve_evidence(args.query, args.top_k, store_path=args.store)
    except OpenAIError:
        print("OpenAI embedding request failed. Check OPENAI_API_KEY, connectivity, and account limits.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as exc:
        print(f"Retrieval failed: {exc}", file=sys.stderr)
        return 1
    for rank, result in enumerate(results, 1):
        chunk = result.chunk
        page = f", page {chunk.page}" if chunk.page is not None else ""
        print(f"[{rank}] score={result.score:.4f} | {chunk.source}{page}")
        print(f"document_id={chunk.document_id} | chunk_id={chunk.chunk_id}")
        print(f"characters={chunk.start_char}:{chunk.end_char}")
        print(chunk.text)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
