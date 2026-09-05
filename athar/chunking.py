"""Page-local overlapping chunks with reproducible identifiers and exact offsets."""
import hashlib
import re
from collections.abc import Iterable

from athar.config import CHUNK_OVERLAP, CHUNK_SIZE, MAX_INPUT_BYTES
from athar.models import Chunk, DocumentPage


def chunk_documents(
    pages: Iterable[DocumentPage], *, chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[Chunk]:
    """Prefer whitespace boundaries, preserving every nonblank span and its provenance.

    Size and overlap are Unicode characters, not tokens. Chunks never cross pages.
    The size cap also bounds worst-case UTF-8 bytes for embedding requests.
    """
    if not 0 <= overlap < chunk_size <= MAX_INPUT_BYTES // 4:
        raise ValueError(f"Require 0 <= overlap < chunk_size <= {MAX_INPUT_BYTES // 4}")
    chunks = []
    for page in pages:
        start = 0
        while start < len(page.text):
            end = min(start + chunk_size, len(page.text))
            if end < len(page.text):
                minimum = start + max(overlap + 1, chunk_size // 2)
                boundaries = list(re.finditer(r"\s+", page.text[minimum:end]))
                if boundaries:
                    end = minimum + boundaries[-1].end()
            text = page.text[start:end]
            if text.strip():
                identity = f"{page.document_id}:{page.page}:{start}:{end}:{text}"
                chunks.append(Chunk(
                    chunk_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                    document_id=page.document_id, source=page.source, page=page.page,
                    text=text, start_char=start, end_char=end,
                ))
            if end == len(page.text):
                break
            start = end - overlap
    return chunks
