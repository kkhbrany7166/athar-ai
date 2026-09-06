"""Local API contracts and real engine orchestration, with external AI mocked."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import numpy as np
from fastapi.testclient import TestClient
from athar.action_updates import ActionMatcher, UpdateDraft, UpdateMatch
from athar.extraction import ActionDraft, DecisionDraft, ExtractionDraft, ground_extraction
from athar.memory_store import load_memory
from server.main import create_app
from server.services import MAX_FILE_BYTES, ServiceError, WorkspaceService


class APITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = WorkspaceService(Path(self.directory.name))
        self.client = TestClient(create_app(self.service))
        # Prevent any accidental billable API operation in this suite.
        self.embedder = Mock(model="offline-test")
        self.embedder.embed.side_effect = lambda texts: np.ones((len(texts), 2), dtype=np.float32)
        self.extractor = Mock(model="offline-test")
        self.extractor.extract.side_effect = self.extract
        self.extracted = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("server.services.OpenAIEmbedder", return_value=self.embedder))
        self.stack.enter_context(patch("server.services.MemoryExtractor", return_value=self.extractor))
        self.stack.enter_context(patch("server.services.ActionMatcher", return_value=self.matcher()))
        self.stack.enter_context(patch("athar.embeddings.OpenAI", side_effect=AssertionError("Network forbidden")))
        self.stack.enter_context(patch("athar.reranking.OpenAI", side_effect=AssertionError("Network forbidden")))

    def extract(self, chunk):
        self.extracted.append(chunk.source)
        meeting = chunk.source == "meeting_03_ar.md"
        decision = DecisionDraft(title="Replace Falcon" if meeting else "Select Falcon",
            description="Grounded test decision", rationale="Schedule reliability", participants=[],
            decision_date_text="3 سبتمبر 2026" if meeting else "12 August 2026", evidence_excerpts=[chunk.text])
        actions = [ActionDraft(description="طلب خطة التنفيذ المحدثة", owner="أحمد", deadline_text="قبل يوم الأحد",
                    status="open", evidence_excerpts=[chunk.text])] if meeting else []
        # Arbitrary upload tests need not contain an explicit dated decision.
        if chunk.source not in {"meeting_03_ar.md", "procurement_plan.md"}:
            return ground_extraction(ExtractionDraft(decisions=[], action_items=[], risks=[]), chunk)
        return ground_extraction(ExtractionDraft(decisions=[decision], action_items=actions, risks=[]), chunk)

    def matcher(self):
        client = Mock()
        def match(**kwargs):
            payload = json.loads(kwargs["input"][1]["content"])
            if "7 سبتمبر 2026" not in payload["new_text"]:
                return SimpleNamespace(status="completed", output_parsed=UpdateMatch(match=None))
            return SimpleNamespace(status="completed", output_parsed=UpdateMatch(match=UpdateDraft(
                candidate_id="a1", update_type="completed", description="Plan received",
                observed_date_text="7 سبتمبر 2026", previous_owner=None, new_owner=None,
                evidence_excerpts=[payload["new_text"].split("\n\n")[1]])))
        client.responses.parse.side_effect = match
        return ActionMatcher(client=client)

    def project(self):
        response = self.client.post("/api/projects", json={"name": "Local project"})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def atlas(self):
        response = self.client.post("/api/projects/atlas/load")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "processing")
        project_id = response.json()["id"]
        self.assertEqual(self.client.get(f"/api/projects/{project_id}").json()["status"], "ready")
        return project_id

    def upload(self, project_id, name="notes.md", data=b"Project notes."):
        return self.client.post("/api/documents/upload", data={"project_id": project_id}, files={"file": (name, data)})

    def test_health_exposes_presence_only(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "synthetic-private-key"}):
            response = self.client.get("/api/health")
        self.assertEqual(response.json(), {"status": "ok", "ai_configured": True})
        self.assertNotIn("synthetic-private-key", response.text)

    def test_create_list_and_restore_project(self):
        project_id = self.project()
        self.assertEqual(self.client.get("/api/projects").json()[0]["id"], project_id)
        self.assertEqual(WorkspaceService(Path(self.directory.name)).get(UUID(project_id)).name, "Local project")

    def test_no_arbitrary_project_paths(self):
        response = self.client.post("/api/process", json={"project_id": "../../.env"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("../../.env", response.text)
        self.assertEqual(self.client.get(f"/api/projects/{uuid4()}").status_code, 404)

    def test_unknown_request_fields_not_echoed(self):
        response = self.client.post("/api/projects", json={"name": "Project", "path": "private-key-data"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private-key-data", response.text)

    def test_upload_stored_under_generated_identity(self):
        project_id = self.project()
        response = self.upload(project_id, "ملاحظات.md", "مشروع جديد".encode())
        self.assertEqual(response.status_code, 201)
        doc = response.json()["documents"][0]
        path = Path(self.directory.name) / project_id / "uploads" / f'{doc["id"]}.md'
        self.assertTrue(path.exists())
        self.assertEqual(doc["filename"], "ملاحظات.md")
        self.assertEqual(doc["status"], "uploaded")
        self.assertNotIn(self.directory.name, response.text)

    def test_traversal_and_unsupported_uploads_rejected(self):
        project_id = self.project()
        for name in ("../bad.md", "nested/bad.txt", "folder\\bad.md", ".env", "x.exe", "x.svg"):
            with self.subTest(name=name):
                self.assertEqual(self.upload(project_id, name).status_code, 400)
        self.assertEqual(list((Path(self.directory.name) / project_id / "uploads").iterdir()), [])

    def test_upload_content_validation(self):
        project_id = self.project()
        for name, data in (("x.md", b"\xff"), ("x.txt", b"\x00abc"), ("x.md", b"   "), ("x.pdf", b"not pdf")):
            with self.subTest(name=name, data=data):
                self.assertEqual(self.upload(project_id, name, data).status_code, 400)

    def test_file_size_limit(self):
        self.assertEqual(self.upload(self.project(), data=b"a" * (MAX_FILE_BYTES + 1)).status_code, 413)

    def test_expected_cors_only_and_foreign_form_write_blocked(self):
        response = self.client.options("/api/process", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:3000")
        response = self.client.post("/api/projects", json={"name": "No"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertEqual(self.service.projects(), [])

    def test_host_boundary_and_secret_paths(self):
        self.assertEqual(self.client.get("/api/health", headers={"host": "evil.example"}).status_code, 400)
        for path in ("/.env", "/uploads/notes.md", "/data/processed/web"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_process_empty_or_not_yet_indexed(self):
        project_id = self.project()
        self.assertEqual(self.client.post("/api/process", json={"project_id": project_id}).status_code, 409)
        self.assertEqual(self.client.get(f"/api/decisions?project_id={project_id}").status_code, 409)

    def test_duplicate_processing_and_upload_during_job_rejected(self):
        project_id = self.project()
        self.upload(project_id)
        self.service.begin(UUID(project_id))
        self.assertEqual(self.client.post("/api/process", json={"project_id": project_id}).status_code, 409)
        self.assertEqual(self.upload(project_id).status_code, 409)

    def test_processing_real_storage_and_evidence(self):
        project_id = self.atlas()
        response = self.client.get(f"/api/decisions?project_id={project_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([d["date"] for d in response.json()["timeline"]], ["2026-08-12", "2026-09-03"])
        memory = load_memory(self.service.snapshot(UUID(project_id)) / "memory.json")
        self.assertEqual(self.extracted, ["procurement_plan.md", "meeting_03_ar.md"])
        self.assertEqual(len(memory.source_chunks), 3)
        for decision in response.json()["timeline"]:
            for ref in decision["evidence_references"]:
                chunk = next(c for c in memory.source_chunks if c.chunk_id == ref["chunk_id"])
                self.assertIn(ref["excerpt"], chunk.text)

    def test_atlas_same_action_id_assignment_and_completion(self):
        project_id = self.atlas()
        actions = self.client.get(f"/api/actions?project_id={project_id}").json()
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["state"], "completed")
        self.assertEqual(action["action"]["status"], "open")
        self.assertEqual(action["history"][0]["event_id"], action["action"]["id"])
        self.assertEqual([event["event_type"] for event in action["history"]], ["assignment", "completed"])
        self.assertEqual(self.client.get(f'/api/actions/{action["action"]["id"]}?project_id={project_id}').json(), action)
        self.assertEqual(self.client.get(f"/api/open-loops?project_id={project_id}").json(), [])

    def test_action_identity_is_scoped_to_project(self):
        project_id = self.atlas()
        other_id = self.atlas()
        action = self.client.get(f"/api/actions?project_id={project_id}").json()[0]
        self.assertEqual(self.client.get(f'/api/actions/{action["action"]["id"]}?project_id={other_id}').status_code, 404)

    def test_pipeline_failure_safe_retryable_and_prior_snapshot_preserved(self):
        project_id = self.atlas()
        prior = self.service.get(UUID(project_id)).snapshot_id
        self.upload(project_id, "new.md")
        with patch.object(self.embedder, "embed", side_effect=RuntimeError("synthetic-provider-secret")), contextlib.redirect_stderr(io.StringIO()) as logs:
            response = self.client.post("/api/process", json={"project_id": project_id})
        current = self.service.get(UUID(project_id))
        self.assertEqual(current.status, "failed")
        self.assertEqual(current.snapshot_id, prior)
        self.assertNotIn("synthetic-provider-secret", response.text + current.model_dump_json() + logs.getvalue())
        self.assertEqual(self.client.get(f"/api/decisions?project_id={project_id}").status_code, 200)
        self.assertEqual(self.client.post("/api/process", json={"project_id": project_id}).status_code, 202)
        self.assertEqual(self.service.get(UUID(project_id)).status, "ready")

    def test_restart_recovers_processing_state(self):
        project_id = self.project()
        self.upload(project_id)
        self.service.begin(UUID(project_id))
        self.service.recover()
        project = self.service.get(UUID(project_id))
        self.assertEqual(project.status, "failed")
        self.assertEqual(project.documents[0].status, "failed")
        self.assertIn("restart", project.error)

    def test_incremental_process_preserves_original_memory_and_actions(self):
        project_id = self.atlas()
        before = self.client.get(f"/api/actions?project_id={project_id}").json()
        self.upload(project_id, "extra.md", b"A document with no commitments.")
        self.client.post("/api/process", json={"project_id": project_id})
        self.assertEqual(self.service.get(UUID(project_id)).status, "ready")
        self.assertEqual(self.client.get(f"/api/actions?project_id={project_id}").json(), before)
        self.assertEqual(self.extracted.count("meeting_03_ar.md"), 1)

    def test_search_calls_existing_engine_with_workspace_scoped_paths(self):
        project_id = self.atlas()
        # Deliberately fail after observing the call; no provider client is constructed.
        with patch("server.services.two_stage_search", side_effect=RuntimeError("private-key-provider-body")) as search:
            response = self.client.post("/api/search", json={"project_id": project_id, "query": "ليش غيرنا المورد؟"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private-key-provider-body", response.text)
        args, kwargs = search.call_args
        self.assertEqual(args, ("ليش غيرنا المورد؟",))
        self.assertTrue(kwargs["store_path"].is_relative_to(self.service._path(UUID(project_id))))

    def test_search_input_limits(self):
        project_id = self.project()
        for query in ("", "  ", "a" * 2001):
            self.assertEqual(self.client.post("/api/search", json={"project_id": project_id, "query": query}).status_code, 422)

    def test_chunked_request_is_bounded_before_multipart_parsing(self):
        response = self.client.post("/api/documents/upload", content=iter([b"a" * (MAX_FILE_BYTES + 65537)]),
            headers={"content-type": "multipart/form-data; boundary=test"})
        self.assertEqual(response.status_code, 413)

    def test_successful_search_serializes_engine_records_and_exact_evidence(self):
        from athar.reranking import two_stage_search
        project_id = self.atlas()
        def offline_search(query, **kwargs):
            return two_stage_search(query, **kwargs, embedder=self.embedder, enabled=False)
        with patch("server.services.two_stage_search", side_effect=offline_search):
            response = self.client.post("/api/search", json={"project_id": project_id, "query": "Falcon"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["rerank_status"], "disabled")
        self.assertTrue(body["results"])
        self.assertEqual(len(body["timeline"]), 2)
        chunks = load_memory(self.service.snapshot(UUID(project_id)) / "memory.json").source_chunks
        for row in body["results"]:
            for reference in row["result"]["evidence_references"]:
                chunk = next(c for c in chunks if c.chunk_id == reference["chunk_id"])
                self.assertIn(reference["excerpt"], chunk.text)
