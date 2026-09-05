"""Extract evidence-backed organizational memory from the existing chunk index."""
import argparse
from pathlib import Path
import sys
from zipfile import BadZipFile

from openai import OpenAIError

from athar.config import EXTRACTION_MODEL, MEMORY_PATH, STORE_PATH
from athar.extraction import ExtractionError, MemoryExtractor
from athar.memory_store import extract_memory, save_memory
from athar.vector_store import LocalVectorStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=STORE_PATH, help="Existing ingested NumPy index")
    parser.add_argument("--output", type=Path, default=MEMORY_PATH, help="JSON memory snapshot to replace")
    parser.add_argument("--model", default=EXTRACTION_MODEL, help="Structured-output-capable OpenAI model")
    args = parser.parse_args(argv)
    if args.store.resolve() == args.output.resolve():
        parser.error("--output must differ from the input index")
    try:
        store = LocalVectorStore.load(args.store)
        memory = extract_memory(list(store.chunks), MemoryExtractor(model=args.model))
        save_memory(memory, args.output)
    except OpenAIError:
        print("Extraction request failed. Check API credentials, model access, connectivity, and quota. "
              "Existing memory was left unchanged.", file=sys.stderr)
        return 1
    except (ExtractionError, OSError, ValueError, KeyError, TypeError, BadZipFile):
        # Do not echo model output, validation payloads, or API error bodies.
        print("Extraction failed: missing/invalid index, unusable structured output, or memory write failure. "
              "Existing memory was left unchanged.", file=sys.stderr)
        return 1
    print(f"Documents processed: {len({chunk.document_id for chunk in store.chunks})}")
    print(f"Chunks processed: {len(store.chunks)}")
    print(f"Decisions extracted: {len(memory.decisions)}")
    print(f"Action items extracted: {len(memory.action_items)}")
    print(f"Risks extracted: {len(memory.risks)}")
    print(f"Items rejected by grounding checks: {len(memory.rejected_items)}")
    print(f"Memory saved to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
