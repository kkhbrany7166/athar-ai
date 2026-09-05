"""Search text and a content-addressed local cache of organizational-memory vectors."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zipfile import BadZipFile

import numpy as np
from numpy.typing import NDArray

from athar.embeddings import OpenAIEmbedder
from athar.memory_store import OrganizationalMemory
from athar.models import ActionItem, Decision, Risk
from athar.vector_store import normalize_vectors

MemoryItem = Decision | ActionItem | Risk
REPRESENTATION_VERSION = 1


def memory_search_text(item: MemoryItem) -> str:
    """Embed organizational fields, excluding IDs, source paths, and repeated quotes."""
    if isinstance(item, Decision):
        fields = [("Decision", item.title), ("Description", item.description),
                  ("Rationale", item.rationale), ("Participants", ", ".join(item.participants)),
                  ("Date", item.decision_date_text)]
    elif isinstance(item, ActionItem):
        fields = [("Action item", item.description), ("Owner", item.owner),
                  ("Deadline", item.deadline_text), ("Status", item.status)]
    else:
        fields = [("Risk", item.description), ("Severity", item.severity), ("Status", item.status)]
    return "\n".join(f"{label}: {value}" for label, value in fields if value and value != "unknown")


def memory_items(memory: OrganizationalMemory) -> list[MemoryItem]:
    """Stable item order also defines deterministic score tie-breaking."""
    return sorted([*memory.decisions, *memory.action_items, *memory.risks], key=lambda item: item.id)


def memory_fingerprint(items: list[MemoryItem], model: str) -> str:
    """Invalidate for content, provenance, model, or representation changes, not timestamps."""
    payload = {"version": REPRESENTATION_VERSION, "model": model,
               "items": [{"kind": type(item).__name__, "record": item.model_dump(mode="json"),
                          "text": memory_search_text(item)} for item in items]}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def cached_memory_vectors(
    items: list[MemoryItem], embedder: OpenAIEmbedder, path: Path, *, dimensions: int,
) -> NDArray[np.float32]:
    """Reuse a matching cache; rebuild missing/stale/corrupt caches atomically.

    Only query embeddings are requested on an unchanged index. Changed snapshots
    rebuild all memory vectors; partial per-item embedding reuse is future work.
    """
    if not items:
        return np.empty((0, dimensions), dtype=np.float32)
    path = Path(path)
    fingerprint = memory_fingerprint(items, embedder.model)
    if path.is_file():
        try:
            with np.load(path, allow_pickle=False) as archive:
                header = json.loads(str(archive["metadata"].item()))
                if (header["fingerprint"] == fingerprint and header["model"] == embedder.model
                        and header["item_ids"] == [item.id for item in items]
                        and header["version"] == REPRESENTATION_VERSION):
                    matrix = normalize_vectors(archive["embeddings"])
                    if matrix.shape == (len(items), dimensions):
                        return matrix
        except (ValueError, KeyError, TypeError, OSError, BadZipFile, EOFError):
            pass  # This is a disposable cache; the validated JSON is authoritative.
    matrix = normalize_vectors(embedder.embed([memory_search_text(item) for item in items]))
    if matrix.shape != (len(items), dimensions):
        raise ValueError("Memory vectors do not match the raw index dimensions; rebuild using the same model")
    header = json.dumps({"version": REPRESENTATION_VERSION, "fingerprint": fingerprint,
                         "model": embedder.model, "item_ids": [item.id for item in items]})
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(stream, embeddings=matrix, metadata=np.array(header))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return matrix
