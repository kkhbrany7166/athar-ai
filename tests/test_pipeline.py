"""Offline contract tests; mocked embeddings do not establish semantic quality."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from athar.chunking import chunk_documents
from athar.embeddings import OpenAIEmbedder
from athar.ingestion import load_document, load_documents
from athar.models import ActionItem, Decision, DocumentPage, Risk
from athar.retrieval import retrieve_evidence
from athar.vector_store import LocalVectorStore
from scripts import ingest, query


def sample_chunks():
    return chunk_documents([
        DocumentPage(document_id="a", source="a.txt", text="Supplier changed."),
        DocumentPage(document_id="b", source="b.pdf", page=2, text="تأجل المشروع."),
    ])


class IngestionTests(unittest.TestCase):
    def test_unicode_sources_and_version_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nested").mkdir()
            path = root / "nested" / "meeting.MD"
            path.write_text("قرار جديد English", encoding="utf-8")
            first = load_documents(root)[0]
            self.assertEqual(first.source, "nested/meeting.MD")
            self.assertIsNone(first.page)
            self.assertEqual(first, load_documents(root)[0])
            path.write_text("قرار مختلف", encoding="utf-8")
            self.assertNotEqual(first.document_id, load_documents(root)[0].document_id)
            (root / "ignored.csv").write_text("ignored")
            self.assertEqual(len(load_documents(root)), 1)
            with self.assertRaises(ValueError):
                load_document(root / "ignored.csv")

    def test_pdf_page_numbers_and_empty_page(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "meeting.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            page = writer.add_blank_page(width=300, height=300)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 200 Td (Supplier changed.) Tj ET")
            page[NameObject("/Contents")] = stream
            writer.write(path)
            with self.assertWarns(UserWarning):
                pages = load_document(path)
            self.assertEqual(len(pages), 1)
            self.assertEqual(pages[0].page, 2)
            self.assertIn("Supplier changed.", pages[0].text)
            self.assertEqual(chunk_documents(pages)[0].page, 2)

    def test_chunk_coverage_overlap_and_stable_ids(self):
        text = "قرار جديد. English decision.\n" * 100
        page = DocumentPage(document_id="id", source="notes.txt", text=text)
        chunks = chunk_documents([page], chunk_size=100, overlap=20)
        self.assertEqual(chunks, chunk_documents([page], chunk_size=100, overlap=20))
        covered = set()
        for chunk in chunks:
            self.assertEqual(chunk.text, text[chunk.start_char:chunk.end_char])
            self.assertLessEqual(len(chunk.text), 100)
            covered.update(range(chunk.start_char, chunk.end_char))
        self.assertEqual(covered, set(range(len(text))))
        for left, right in zip(chunks, chunks[1:]):
            self.assertEqual(left.end_char - right.start_char, 20)
        for size, overlap in [(0, 0), (10, 10), (10, -1), (3000, 0)]:
            with self.assertRaises(ValueError):
                chunk_documents([page], chunk_size=size, overlap=overlap)
        self.assertEqual(chunk_documents([page.model_copy(update={"text": "  "})]), [])


class VectorTests(unittest.TestCase):
    def test_roundtrip_ranking_and_scores(self):
        store = LocalVectorStore(sample_chunks(), [[3, 0], [0, 8]], model="test")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.npz"
            store.save(path)
            loaded = LocalVectorStore.load(path)
            results = loaded.search([0, 2], top_k=9)
            self.assertEqual(results[0].chunk, sample_chunks()[1])
            self.assertAlmostEqual(results[0].score, 1)
            self.assertAlmostEqual(results[1].score, 0)
            self.assertEqual(loaded.model, "test")
            self.assertEqual(loaded.search([1, 1])[0].chunk, sample_chunks()[0])
            store.save(path)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_invalid_vectors(self):
        for vectors in ([[0, 0], [1, 0]], [[float("nan"), 0], [1, 0]], [[1, 0]], [1, 2]):
            with self.assertRaises(ValueError):
                LocalVectorStore(sample_chunks(), vectors, model="test")
        store = LocalVectorStore(sample_chunks(), np.eye(2), model="test")
        for vector in ([0, 0], [1], [float("inf"), 1]):
            with self.assertRaises(ValueError):
                store.search(vector)
        with self.assertRaises(ValueError):
            store.search([1, 0], 0)

    def test_failed_save_preserves_previous_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.npz"
            store = LocalVectorStore(sample_chunks(), np.eye(2), model="test")
            store.save(path)
            original = path.read_bytes()
            with patch("athar.vector_store.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    store.save(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


class EmbeddingTests(unittest.TestCase):
    def test_batches_and_response_order(self):
        client = Mock()
        client.embeddings.create.side_effect = [
            SimpleNamespace(data=[SimpleNamespace(index=1, embedding=[0, 1]), SimpleNamespace(index=0, embedding=[1, 0])]),
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[1, 1])]),
        ]
        embedder = OpenAIEmbedder(client=client, batch_size=2)
        np.testing.assert_array_equal(embedder.embed(["English", "عربي", "mixed عربي"]), [[1, 0], [0, 1], [1, 1]])
        self.assertEqual(client.embeddings.create.call_count, 2)
        self.assertEqual(client.embeddings.create.call_args_list[0].kwargs["input"], ["English", "عربي"])

    def test_validation_before_network(self):
        client = Mock()
        embedder = OpenAIEmbedder(client=client)
        for texts in ([], [" "], ["valid", "ع" * 5000]):
            with self.assertRaises(ValueError):
                embedder.embed(texts)
        client.embeddings.create.assert_not_called()

    def test_request_byte_budget(self):
        client = Mock()
        def response(**kwargs):
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1, 0]) for i in range(len(kwargs["input"]))])
        client.embeddings.create.side_effect = response
        OpenAIEmbedder(client=client, batch_size=100).embed(["a" * 8000] * 40)
        self.assertEqual(client.embeddings.create.call_count, 2)
        for call in client.embeddings.create.call_args_list:
            self.assertLessEqual(sum(len(x.encode("utf-8")) for x in call.kwargs["input"]), 250_000)

    def test_retrieval_model_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "index.npz"
            LocalVectorStore(sample_chunks(), np.eye(2), model="test").save(path)
            embedder = Mock(model="test")
            embedder.embed.return_value = np.array([[0, 1]])
            result = retrieve_evidence("ليش تأجل المشروع؟", 1, store_path=path, embedder=embedder)
            self.assertEqual(result[0].chunk.page, 2)
            embedder.embed.assert_called_once_with(["ليش تأجل المشروع؟"])
            embedder.model = "different"
            with self.assertRaises(ValueError):
                retrieve_evidence("question", store_path=path, embedder=embedder)


class ContractTests(unittest.TestCase):
    def test_memory_models(self):
        reference = sample_chunks()[0].model_dump(include={"document_id", "chunk_id", "source", "page"})
        decision = Decision(id="d", title="Change", description="Change supplier", evidence_references=[reference])
        self.assertIsNone(decision.rationale)
        self.assertEqual(ActionItem(id="a", description="Review").status, "unknown")
        self.assertEqual(Risk(id="r", description="Delay").severity, "unknown")
        with self.assertRaises(ValidationError):
            Risk(id="r", description="Delay", severity="invented")

    def test_cli_end_to_end_with_mock_embeddings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            documents.mkdir()
            (documents / "meeting.txt").write_text("تأجل المشروع بسبب الاختبارات", encoding="utf-8")
            path = root / "index.npz"
            with patch.object(OpenAIEmbedder, "embed", return_value=np.array([[1, 0]])), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(ingest.main(["--documents", str(documents), "--store", str(path)]), 0)
                self.assertEqual(query.main(["ليش تأجل المشروع؟", "--store", str(path)]), 0)
            self.assertIn("score=1.0000", output.getvalue())
            self.assertIn("تأجل المشروع بسبب الاختبارات", output.getvalue())
            (documents / "meeting.txt").unlink()
            before = path.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ingest.main(["--documents", str(documents), "--store", str(path)]), 1)
                self.assertEqual(query.main(["question", "--store", str(root / "missing.npz")]), 1)
            self.assertEqual(path.read_bytes(), before)

    def test_eval_references_resolve(self):
        root = Path(__file__).resolve().parents[1] / "evals"
        for line in (root / "retrieval_dataset.jsonl").read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            sources = [(root / "fixtures" / source).read_text(encoding="utf-8") for source in record["expected_sources"]]
            self.assertTrue(any(record["expected_evidence"] in text for text in sources))


if __name__ == "__main__":
    unittest.main()
