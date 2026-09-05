"""Project-local environment loading and defaults shared by both CLI entry points."""
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

DOCUMENTS_DIR = PROJECT_ROOT / "data" / "documents"
STORE_PATH = PROJECT_ROOT / "data" / "processed" / "vector_store.npz"
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
EMBEDDING_BATCH_SIZE = 32
# Conservative UTF-8 byte bounds avoid needing a tokenizer dependency.
MAX_INPUT_BYTES = 8000
MAX_BATCH_BYTES = 250_000

EXTRACTION_MODEL = "gpt-4.1-mini-2025-04-14"
MEMORY_PATH = PROJECT_ROOT / "data" / "processed" / "organizational_memory.json"
MEMORY_INDEX_PATH = PROJECT_ROOT / "data" / "processed" / "memory_vectors.npz"
RERANK_MODEL = "gpt-4.1-mini-2025-04-14"
