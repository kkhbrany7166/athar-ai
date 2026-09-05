"""Extract UTF-8 text and PDF pages while preserving source identity."""
import hashlib
import io
from pathlib import Path
import warnings

from pypdf import PdfReader

from athar.models import DocumentPage

SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".pdf"})


def load_document(path: Path, *, source_root: Path | None = None) -> list[DocumentPage]:
    """Read a source; identity includes relative path and the original file bytes."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported document type: {path.suffix}")
    source = path.relative_to(source_root).as_posix() if source_root else path.name
    raw = path.read_bytes()
    document_id = hashlib.sha256(source.encode("utf-8") + b"\0" + raw).hexdigest()
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError(f"Encrypted PDF is not supported: {source}")
        pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
    else:
        pages = [(None, raw.decode("utf-8-sig"))]
    result = []
    for number, text in pages:
        if not text.strip():
            warnings.warn(f"No extractable text: {source}, page={number}; OCR is not implemented", stacklevel=2)
            continue
        result.append(DocumentPage(document_id=document_id, source=source, page=number, text=text))
    return result


def load_documents(directory: Path) -> list[DocumentPage]:
    """Read supported files recursively in deterministic order; fail on unreadable input."""
    directory = Path(directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"Document directory does not exist: {directory}")
    pages = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            pages.extend(load_document(path, source_root=directory))
    return pages
