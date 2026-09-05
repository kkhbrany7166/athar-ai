"""Rebuild the local evidence index from a directory of documents."""
import argparse
from pathlib import Path
import sys

from openai import OpenAIError
from pypdf.errors import PyPdfError

from athar.chunking import chunk_documents
from athar.config import DOCUMENTS_DIR, STORE_PATH
from athar.embeddings import OpenAIEmbedder
from athar.ingestion import load_documents
from athar.vector_store import LocalVectorStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=Path, default=DOCUMENTS_DIR)
    parser.add_argument("--store", type=Path, default=STORE_PATH)
    args = parser.parse_args(argv)
    try:
        pages = load_documents(args.documents)
        chunks = chunk_documents(pages)
        if not chunks:
            print("No extractable documents found; existing index was left unchanged.", file=sys.stderr)
            return 1
        embedder = OpenAIEmbedder()
        vectors = embedder.embed([chunk.text for chunk in chunks])
        LocalVectorStore(chunks, vectors, model=embedder.model).save(args.store)
    except OpenAIError:
        print("OpenAI embedding request failed. Check OPENAI_API_KEY, connectivity, and account limits.", file=sys.stderr)
        return 1
    except (OSError, ValueError, PyPdfError) as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1
    print(f"Indexed {len({page.document_id for page in pages})} documents, "
          f"{len(pages)} text pages, and {len(chunks)} chunks into {args.store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
