"""Filesystem workspaces and orchestration; all AI/state rules live in athar.

One local server process owns writes. Completed snapshots are immutable and are
published by atomically switching project metadata, so failed jobs keep prior data.
"""
import json
from pathlib import Path
import os
import re
import shutil
import threading
from uuid import UUID, uuid4

from athar.action_updates import ActionLedger, ActionMatcher, load_ledger, process_updates, save_ledger
from athar.chunking import chunk_documents
from athar.config import PROJECT_ROOT
from athar.embeddings import OpenAIEmbedder
from athar.extraction import MemoryExtractor
from athar.ingestion import load_document
from athar.memory_store import OrganizationalMemory, extract_memory, load_memory, save_memory
from athar.open_loops import list_actions
from athar.reranking import two_stage_search
from athar.timeline import decision_timeline
from athar.vector_store import LocalVectorStore
from server.schemas import DecisionResponse, Document, Project

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS = 30
SAFE_PROCESS_ERROR = "Processing could not finish. Check that documents contain readable text, and that the Python server has API access and connectivity. Your files are retained; retry processing."


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class WorkspaceService:
    def __init__(self, root: Path = PROJECT_ROOT / "data/processed/web"):
        self.root = Path(root)
        self.lock = threading.RLock()

    def recover(self):
        """An interrupted in-process job is retryable, never permanently Processing."""
        with self.lock:
            for project in self.projects():
                if project.status == "processing":
                    self._failed(project, "Processing was interrupted by a server restart. Retry to continue.")

    def _path(self, project_id: UUID) -> Path:
        return self.root / str(UUID(str(project_id)))

    def _save(self, project: Project):
        path = self._path(project.id) / "project.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def get(self, project_id: UUID) -> Project:
        path = self._path(project_id) / "project.json"
        if not path.is_file():
            raise ServiceError("Project not found.", 404)
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def projects(self) -> list[Project]:
        return sorted((self.get(UUID(p.parent.name)) for p in self.root.glob("*/project.json")),
                      key=lambda p: p.created_at, reverse=True)

    def create(self, name: str, *, synthetic: bool = False) -> Project:
        with self.lock:
            project = Project(id=uuid4(), name=name, synthetic=synthetic)
            (self._path(project.id) / "uploads").mkdir(parents=True)
            self._save(project)
            return project

    def upload(self, project_id: UUID, filename: str, data: bytes, *, kind="document") -> Project:
        # Keep a human filename only as metadata. Disk filenames are generated UUIDs.
        if (not filename or len(filename) > 180 or filename.startswith(".")
                or re.search(r'[/\\\x00-\x1f\x7f]', filename)):
            raise ServiceError("Use a plain filename without folders or control characters.")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".pdf"}:
            raise ServiceError("Supported files: .txt, .md and text-based .pdf.")
        if not data or len(data) > MAX_FILE_BYTES:
            raise ServiceError("Upload a nonempty file up to 10 MB.", 413)
        if suffix == ".pdf":
            if not data.startswith(b"%PDF-"):
                raise ServiceError("This file does not have a valid PDF header.")
        else:
            try:
                decoded = data.decode("utf-8-sig")
            except UnicodeError:
                raise ServiceError("Text and Markdown files must use UTF-8 encoding.") from None
            if not decoded.strip() or "\x00" in decoded:
                raise ServiceError("Upload a file containing readable text.")
        with self.lock:
            project = self.get(project_id)
            if project.status == "processing":
                raise ServiceError("Wait for processing to finish before uploading.", 409)
            if len(project.documents) >= MAX_DOCUMENTS:
                raise ServiceError("This local workspace supports up to 30 documents.", 409)
            doc = Document(id=uuid4(), filename=filename, size=len(data), kind=kind)
            target = self._path(project_id) / "uploads" / f"{doc.id}{suffix}"
            target.write_bytes(data)
            project.documents.append(doc)
            project.status, project.stage, project.error = "uploaded", "Documents uploaded. Ready to process.", None
            self._save(project)
            return project

    def atlas(self) -> Project:
        project = self.create("Project Atlas", synthetic=True)
        for filename in ("procurement_plan.md", "meeting_03_ar.md", "meeting_07_ar.md"):
            project = self.upload(project.id, filename,
                (PROJECT_ROOT / "examples/project_atlas" / filename).read_bytes(),
                kind="followup" if filename == "meeting_07_ar.md" else "document")
        return project

    def begin(self, project_id: UUID) -> Project:
        with self.lock:
            project = self.get(project_id)
            if project.status == "processing":
                raise ServiceError("This project is already processing.", 409)
            pending = [d for d in project.documents if d.status != "ready"]
            if not pending:
                raise ServiceError("Upload new documents before processing.", 409)
            for doc in pending:
                doc.status = "processing"
            project.status, project.stage, project.error = "processing", "Reading and validating documents…", None
            self._save(project)
            return project

    def _stage(self, project_id: UUID, message: str):
        with self.lock:
            project = self.get(project_id)
            project.stage = message
            self._save(project)

    def _failed(self, project: Project, message: str):
        project.status, project.stage, project.error = "failed", "Processing needs attention.", message
        for doc in project.documents:
            if doc.status == "processing":
                doc.status = "failed"
        self._save(project)

    def snapshot(self, project_id: UUID) -> Path:
        project = self.get(project_id)
        if project.snapshot_id is None:
            raise ServiceError("Process project documents first.", 409)
        return self._path(project_id) / "snapshots" / str(project.snapshot_id)

    def process(self, project_id: UUID):
        """Background job: calls engine functions, then atomically publishes a snapshot."""
        target = None
        try:
            project = self.get(project_id)
            pending = [d for d in project.documents if d.status == "processing"]
            normal, followup = [], []
            for doc in pending:
                path = self._path(project_id) / "uploads" / f"{doc.id}{Path(doc.filename).suffix.lower()}"
                pages = load_document(path)
                if not pages:
                    raise ServiceError("A document has no readable text. Scanned PDFs need OCR before upload.")
                # Preserve server-generated identity while showing the original source filename.
                pages = [p.model_copy(update={"source": doc.filename}) for p in pages]
                (followup if doc.kind == "followup" else normal).extend(chunk_documents(pages))
            snapshot_id = uuid4()
            target = self._path(project_id) / "snapshots" / str(snapshot_id)
            target.mkdir(parents=True)
            embedder = OpenAIEmbedder()
            previous = self.snapshot(project_id) if project.snapshot_id else None
            self._stage(project_id, "Extracting decisions, commitments and risks…")
            added = extract_memory(normal, MemoryExtractor())
            old = load_memory(previous / "memory.json") if previous else None
            chunks = [*(old.source_chunks if old else []), *normal, *followup]
            memory = OrganizationalMemory(
                extraction_model=added.extraction_model, source_chunks=chunks,
                decisions=[*(old.decisions if old else []), *added.decisions],
                action_items=[*(old.action_items if old else []), *added.action_items],
                risks=[*(old.risks if old else []), *added.risks],
                rejected_items=[*(old.rejected_items if old else []), *added.rejected_items])
            self._stage(project_id, "Matching later evidence to original commitments…")
            if previous:
                ledger = load_ledger(previous / "actions.json")
                ledger = process_updates(ledger, normal, cache_path=target / "action_vectors.npz",
                    embedder=embedder, matcher=ActionMatcher()).ledger
                ledger = ActionLedger(actions=[*ledger.actions, *added.action_items], source_chunks=chunks,
                    updates=ledger.updates, processed_sources=ledger.processed_sources)
            else:
                ledger = ActionLedger.from_memory(memory)
            if followup:
                ledger = process_updates(ledger, followup, cache_path=target / "action_vectors.npz",
                    embedder=embedder, matcher=ActionMatcher()).ledger
            self._stage(project_id, "Building searchable evidence and publishing results…")
            vectors = embedder.embed([c.text for c in chunks])
            LocalVectorStore(chunks, vectors, model=embedder.model).save(target / "vectors.npz")
            save_memory(memory, target / "memory.json")
            save_ledger(ledger, target / "actions.json")
            with self.lock:
                project = self.get(project_id)
                project.snapshot_id = snapshot_id
                project.status, project.stage, project.error = "ready", "Project memory is ready to explore.", None
                for doc in project.documents:
                    doc.status = "ready"
                self._save(project)
        except Exception:
            # Never log/provider-stringify an exception or send it to the browser.
            with self.lock:
                self._failed(self.get(project_id), SAFE_PROCESS_ERROR)
            if target is not None:
                shutil.rmtree(target, ignore_errors=True)

    def decisions(self, project_id: UUID) -> DecisionResponse:
        memory = load_memory(self.snapshot(project_id) / "memory.json")
        return DecisionResponse(timeline=decision_timeline(memory.decisions, source_chunks=memory.source_chunks),
                                risks=memory.risks, rejected_records=len(memory.rejected_items))

    def actions(self, project_id: UUID, *, unresolved_only=False):
        return list_actions(load_ledger(self.snapshot(project_id) / "actions.json"), unresolved_only=unresolved_only)

    def search(self, project_id: UUID, query: str, top_k: int):
        path = self.snapshot(project_id)
        return two_stage_search(query, top_k=top_k, candidate_count=8, store_path=path / "vectors.npz",
                                memory_path=path / "memory.json", cache_path=path / "memory_vectors.npz")
