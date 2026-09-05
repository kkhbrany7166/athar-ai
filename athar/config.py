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
