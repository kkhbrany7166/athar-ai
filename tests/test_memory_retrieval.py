"""Deterministic vectors test ranking contracts, never live multilingual accuracy."""
import contextlib
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from pydantic import ValidationError

from athar.memory_index import cached_memory_vectors, memory_items, memory_search_text
from athar.memory_retrieval import RankingConfig, rank_results, search_memory
from athar.memory_store import OrganizationalMemory, save_memory
from athar.models import ActionItem, Chunk, Decision, EvidenceReference, Risk
from athar.timeline import decision_timeline
from athar.vector_store import LocalVectorStore
from scripts.search_memory import main
from athar.reranking import rerank_candidates


def fixture():
    texts = ["On 12 August 2026, the team selected Cedar for its experience.",
             "3 سبتمبر 2026: اتفق الفريق على استبدال Cedar بشركة Maple بسبب التأخير.",
             "أحمد سيرسل الخطة يوم الأحد. التأخير يهدد الإطلاق.",
             "The archive retention setting is 90 days."]
    chunks = [Chunk(document_id=f"doc-{i}", chunk_id=f"chunk-{i}", source=f"source-{i}.md",
                    page=None, text=text, start_char=0, end_char=len(text)) for i, text in enumerate(texts)]
    refs = [EvidenceReference(document_id=c.document_id, chunk_id=c.chunk_id,
            source=c.source, page=c.page, excerpt=c.text) for c in chunks]
    initial = Decision(id="initial", title="Select Cedar", description=texts[0],
                       rationale="Experience", decision_date="2026-08-12", decision_date_text="12 August 2026",
                       evidence_references=[refs[0]])
    replacement = Decision(id="replacement", title="استبدال Cedar بشركة Maple", description=texts[1],
                           rationale="التأخير", decision_date="2026-09-03", decision_date_text="3 سبتمبر 2026",
                           evidence_references=[refs[1]])
    action = ActionItem(id="action", description="إرسال الخطة", owner="أحمد", deadline_text="يوم الأحد",
                        status="open", evidence_references=[refs[2]])
    risk = Risk(id="risk", description="التأخير يهدد الإطلاق", status="open", evidence_references=[refs[2]])
    memory = OrganizationalMemory(extraction_model="mock", source_chunks=chunks,
                                   decisions=[initial, replacement], action_items=[action], risks=[risk])
    return memory


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.memory = fixture()
        self.items = memory_items(self.memory)

    def scores(self, best):
        return [0.9 if item.id == best else 0.1 for item in self.items]

    def test_direct_decision_competes_with_raw_document(self):
        result = rank_results(self.items, self.scores("replacement"), self.memory.source_chunks,
                              [0.95, 0.92, 0.2, 0.1], top_k=3)
        self.assertEqual(result[0].item_id, "replacement")
        self.assertAlmostEqual(result[0].score, 0.98)
        self.assertAlmostEqual(result[0].cosine_score, 0.9)
        self.assertEqual(result[1].result_type, "document")
        self.assertEqual(result[0].evidence_references, self.memory.decisions[1].evidence_references)

    def test_action_owner_and_risk_queries(self):
        for item_id, kind in (("action", "action_item"), ("risk", "risk")):
            with self.subTest(kind=kind):
                result = rank_results(self.items, self.scores(item_id), [], [], top_k=1)
                self.assertEqual(result[0].result_type, kind)
                self.assertEqual(result[0].item_id, item_id)

    def test_no_relevant_memory_raw_fallback(self):
        result = rank_results(self.items, [0.1] * len(self.items), self.memory.source_chunks,
                              [0.1, 0.2, 0.3, 0.9])
        self.assertTrue(all(item.result_type == "document" for item in result))
        self.assertEqual(result[0].chunk.chunk_id, "chunk-3")

    def test_bonus_not_unconditional_priority_and_can_be_disabled(self):
        result = rank_results(self.items, [0.3] * len(self.items), self.memory.source_chunks,
                              [0.95, 0.1, 0.1, 0.1])
        self.assertEqual(result[0].result_type, "document")
        result = rank_results(self.items, self.scores("replacement"), self.memory.source_chunks,
                              [0.95, 0.1, 0.1, 0.1], ranking=RankingConfig(memory_bonus=0))
        self.assertEqual(result[0].result_type, "document")

    def test_invalid_ranking_and_score_alignment(self):
        with self.assertRaises(ValidationError):
            RankingConfig(memory_bonus=float("nan"))
        with self.assertRaises(ValueError):
            rank_results(self.items, [], [], [])
        with self.assertRaises(ValueError):
            rank_results([], [], [], [], top_k=0)

    def test_search_text_preserves_fields_without_provenance_noise(self):
        for item in self.items:
            text = memory_search_text(item)
            self.assertIn(item.description, text)
            self.assertNotIn("source-", text)
            self.assertNotIn("chunk-", text)
            self.assertNotIn("doc-", text)
            self.assertNotIn("unknown", text)
        self.assertIn("أحمد", memory_search_text(self.memory.action_items[0]))
        self.assertIn("التأخير", memory_search_text(self.memory.decisions[1]))


class CacheAndSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.store_path, self.memory_path, self.cache_path = (root / name for name in ("raw.npz", "memory.json", "cache.npz"))
        self.memory = fixture()
        self.items = memory_items(self.memory)
        save_memory(self.memory, self.memory_path)
        LocalVectorStore(self.memory.source_chunks, np.eye(4), model="test").save(self.store_path)
        self.embedder = Mock(model="test")
        self.vectors = {memory_search_text(item): np.eye(4)[i] for i, item in enumerate(self.items)}

    def use_query(self, query, item_id):
        self.vectors[query] = np.eye(4)[next(i for i, item in enumerate(self.items) if item.id == item_id)]
        self.embedder.embed.side_effect = lambda texts: np.array([self.vectors[text] for text in texts])

    def search(self, query, **kwargs):
        return search_memory(query, store_path=self.store_path, memory_path=self.memory_path,
                             cache_path=self.cache_path, embedder=self.embedder, **kwargs)

    def test_bilingual_and_mixed_queries_use_one_pipeline(self):
        cases = [("ليش اختاروا المورد في البداية؟", "initial"),
                 ("Why did the team replace the vendor?", "replacement"),
                 ("وش صار مع Maple vendor؟", "replacement"),
                 ("What must Ahmed deliver?", "action"),
                 ("What threatens launch?", "risk")]
        for query, item_id in cases:
            self.use_query(query, item_id)
            response = self.search(query, top_k=1)
            self.assertEqual(response.results[0].item_id, item_id)
            self.assertEqual(self.embedder.embed.call_args.args[0], [query])
        # First query embeds the corpus once, then each query embeds only itself.
        self.assertEqual(self.embedder.embed.call_count, len(cases) + 1)

    def test_unchanged_cache_survives_timestamp_changes_and_reload(self):
        self.use_query("question", "initial")
        self.search("question")
        original = self.cache_path.read_bytes()
        self.memory = self.memory.model_copy(update={"created_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
        save_memory(self.memory, self.memory_path)
        self.embedder.embed.reset_mock()
        self.search("question")
        self.embedder.embed.assert_called_once_with(["question"])
        self.assertEqual(self.cache_path.read_bytes(), original)

    def test_content_changes_and_corrupt_cache_trigger_rebuild(self):
        self.use_query("question", "initial")
        self.search("question")
        changed = self.memory.decisions[0].model_copy(update={"title": "Updated selection wording"})
        self.memory.decisions[0] = changed
        save_memory(self.memory, self.memory_path)
        self.vectors[memory_search_text(changed)] = np.eye(4)[1]
        self.embedder.embed.reset_mock()
        self.search("question")
        self.assertEqual(self.embedder.embed.call_count, 2)
        self.cache_path.write_bytes(b"corrupted cache")
        self.embedder.embed.reset_mock()
        self.search("question")
        self.assertEqual(self.embedder.embed.call_count, 2)

    def test_failed_cache_rebuild_preserves_previous_cache(self):
        self.use_query("question", "initial")
        self.search("question")
        original = self.cache_path.read_bytes()
        changed = self.items[0].model_copy(update={"description": "changed"})
        self.embedder.embed.side_effect = OSError("embedding failed")
        with self.assertRaises(OSError):
            cached_memory_vectors([changed], self.embedder, self.cache_path, dimensions=4)
        self.assertEqual(self.cache_path.read_bytes(), original)

    def test_atomic_cache_write_failure_preserves_previous_cache(self):
        self.use_query("question", "initial")
        self.search("question")
        original = self.cache_path.read_bytes()
        changed = self.items[0].model_copy(update={"description": "Changed description"})
        self.embedder.embed.side_effect = None
        self.embedder.embed.return_value = np.ones((1, 4))
        with patch("athar.memory_index.os.replace", side_effect=OSError("write failure")):
            with self.assertRaises(OSError):
                cached_memory_vectors([changed], self.embedder, self.cache_path, dimensions=4)
        self.assertEqual(self.cache_path.read_bytes(), original)
        self.assertEqual(sorted(path.name for path in self.cache_path.parent.iterdir()),
                         ["cache.npz", "memory.json", "raw.npz"])

    def test_model_change_and_dimension_mismatch(self):
        self.use_query("question", "initial")
        self.search("question")
        self.embedder.model = "different"
        with self.assertRaises(ValueError):
            self.search("question")
        self.embedder.embed.side_effect = None
        self.embedder.embed.return_value = np.ones((len(self.items), 4))
        cached_memory_vectors(self.items, self.embedder, self.cache_path, dimensions=4)
        with np.load(self.cache_path, allow_pickle=False) as archive:
            self.assertEqual(json.loads(archive['metadata'].item())['model'], "different")
        with self.assertRaises(ValueError):
            cached_memory_vectors(self.items, self.embedder, self.cache_path, dimensions=5)

    def test_missing_and_empty_memory_fall_back_without_corpus_embeddings(self):
        self.use_query("question", "initial")
        self.memory_path.unlink()
        response = self.search("question")
        self.assertFalse(response.memory_available)
        self.assertTrue(all(item.result_type == "document" for item in response.results))
        self.embedder.embed.assert_called_once_with(["question"])
        self.assertFalse(self.cache_path.exists())
        empty = OrganizationalMemory(extraction_model="test", source_chunks=self.memory.source_chunks)
        save_memory(empty, self.memory_path)
        self.embedder.embed.reset_mock()
        self.assertTrue(self.search("question").memory_available)
        self.embedder.embed.assert_called_once_with(["question"])

    def test_stale_sources_and_invalid_arguments_fail_before_api(self):
        self.use_query("question", "initial")
        for kwargs in ({"top_k": 0},):
            with self.assertRaises(ValueError):
                self.search("question", **kwargs)
        with self.assertRaises(ValueError):
            self.search(" ")
        with self.assertRaises(ValueError):
            self.search("ع" * 5000)
        LocalVectorStore([self.memory.source_chunks[-1]], [[1, 0, 0, 0]], model="test").save(self.store_path)
        with self.assertRaisesRegex(ValueError, "stale"):
            self.search("question")
        self.embedder.embed.assert_not_called()

    def test_cli_output_and_safe_errors(self):
        self.use_query("question", "initial")
        response = self.search("question")
        with patch("scripts.search_memory.two_stage_search", return_value=rerank_candidates("question", response, enabled=False)), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["question", "--timeline"]), 0)
        self.assertIn("DECISION", output.getvalue())
        self.assertIn("DOCUMENT", output.getvalue())
        self.assertIn("Decision timeline", output.getvalue())
        with patch("scripts.search_memory.two_stage_search", side_effect=ValueError("synthetic-secret")), contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(["question"]), 1)
        self.assertNotIn("synthetic-secret", error.getvalue())


class TimelineTests(unittest.TestCase):
    def test_multiple_decisions_ordered_without_entity_merging(self):
        memory = fixture()
        entries = decision_timeline(reversed(memory.decisions), source_chunks=memory.source_chunks)
        self.assertEqual([entry.decision_id for entry in entries], ["initial", "replacement"])
        self.assertEqual([entry.date for entry in entries], [date(2026, 8, 12), date(2026, 9, 3)])
        self.assertEqual(entries[1].rationale, "التأخير")
        self.assertEqual(entries[1].evidence_references, memory.decisions[1].evidence_references)

    def test_unknown_and_unverified_dates_remain_unknown(self):
        memory = fixture()
        initial, replacement = memory.decisions
        unknown = initial.model_copy(update={"id": "unknown", "decision_date": None, "decision_date_text": None})
        wrong = initial.model_copy(update={"id": "wrong", "decision_date": date(3993, 1, 1)})
        entries = decision_timeline([wrong, replacement, unknown, initial, initial], source_chunks=memory.source_chunks)
        self.assertEqual(len(entries), 4)
        self.assertEqual([entry.decision_id for entry in entries[:2]], ["initial", "replacement"])
        self.assertTrue(all(entry.date is None for entry in entries[2:]))
        self.assertEqual(entries[-1].date_status, "unverified")

    def test_tampered_source_rejected(self):
        memory = fixture()
        with self.assertRaises(ValueError):
            decision_timeline(memory.decisions, source_chunks=[])


class EvaluationDatasetTests(unittest.TestCase):
    def test_memory_labels_are_well_formed(self):
        path = Path(__file__).resolve().parents[1] / "evals" / "memory_retrieval_dataset.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        for row in rows:
            self.assertTrue(row["query"].strip())
            self.assertIn(row["query_language"], {"ar", "en", "mixed"})
            self.assertTrue(row["expected_items"])
            self.assertTrue(row["expected_top1"])
            for index in row["expected_top1"]:
                self.assertTrue(0 <= index < len(row["expected_items"]))
            for target in row["expected_items"]:
                self.assertIn(target["result_type"], {"decision", "action_item", "risk"})
                self.assertTrue(target["source"])
                self.assertTrue(target["evidence_contains"].strip())
