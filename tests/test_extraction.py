"""Mocked structured responses test pipeline contracts, not live model accuracy."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from openai import OpenAIError
from pydantic import ValidationError

from athar.extraction import (
    ActionDraft, DecisionDraft, ExtractionDraft, ExtractionError,
    MemoryExtractor, RiskDraft, parse_explicit_date,
)
from athar.memory_store import extract_memory, load_memory, save_memory
from athar.models import Chunk, Decision, EvidenceReference
from athar.vector_store import LocalVectorStore
from scripts.extract_memory import main


def chunk(text: str, chunk_id: str = "chunk-1") -> Chunk:
    return Chunk(document_id="document-1", chunk_id=chunk_id, source="meeting.md",
                 page=2, text=text, start_char=10, end_char=10 + len(text))


def decision(text: str, **updates) -> DecisionDraft:
    fields = dict(title="Vendor decision", description=text, rationale=None,
                  participants=[], decision_date_text=None, evidence_excerpts=[text])
    fields.update(updates)
    return DecisionDraft(**fields)


def action(text: str, **updates) -> ActionDraft:
    fields = dict(description=text, owner=None, deadline_text=None,
                  status="unknown", evidence_excerpts=[text])
    fields.update(updates)
    return ActionDraft(**fields)


def draft(*, decisions=(), action_items=(), risks=()) -> ExtractionDraft:
    return ExtractionDraft(decisions=list(decisions), action_items=list(action_items), risks=list(risks))


def extractor(output: ExtractionDraft, status: str = "completed") -> MemoryExtractor:
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status=status, output_parsed=output)
    return MemoryExtractor(client=client)


class ExtractionTests(unittest.TestCase):
    def test_arabic_decision(self):
        text = "اتفق الفريق على تغيير المورد بسبب تأخر التسليم."
        result = extractor(draft(decisions=[decision(text, rationale="تأخر التسليم")])).extract(chunk(text))
        self.assertEqual(result.decisions[0].rationale, "تأخر التسليم")
        self.assertEqual(result.decisions[0].evidence_references[0].excerpt, text)

    def test_english_decision_explicit_date(self):
        text = "On 12 August 2026, Sara selected Cedar because delivery was faster."
        result = extractor(draft(decisions=[decision(text, rationale="Faster delivery", participants=["Sara"], decision_date_text="12 August 2026")])).extract(chunk(text))
        self.assertEqual(result.decisions[0].decision_date, date(2026, 8, 12))
        self.assertEqual(result.decisions[0].participants, ["Sara"])

    def test_arabic_action_and_relative_deadline(self):
        text = "تم تكليف أحمد بإرسال الخطة قبل يوم الأحد."
        result = extractor(draft(action_items=[action(text, owner="أحمد", deadline_text="قبل يوم الأحد", status="open")])).extract(chunk(text))
        item = result.action_items[0]
        self.assertEqual(item.owner, "أحمد")
        self.assertEqual(item.status, "open")
        self.assertIsNone(item.deadline)
        self.assertEqual(item.deadline_text, "قبل يوم الأحد")

    def test_code_switched_text_and_sdk_contract(self):
        text = "قرر أحمد اعتماد Nova Technologies لتنفيذ API integration."
        engine = extractor(draft(decisions=[decision(text, participants=["أحمد"])]))
        result = engine.extract(chunk(text))
        self.assertEqual(result.decisions[0].participants, ["أحمد"])
        kwargs = engine._client.responses.parse.call_args.kwargs
        self.assertIs(kwargs["text_format"], ExtractionDraft)
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["input"][1]["content"], text)
        schema = json.dumps(ExtractionDraft.model_json_schema())
        for forbidden in ('"document_id"', '"chunk_id"', '"source"', '"page"', '"id"'):
            self.assertNotIn(forbidden, schema)

    def test_discussion_without_decision(self):
        result = extractor(draft()).extract(chunk("Could we consider another supplier? No decision was made."))
        self.assertEqual(result.decisions, [])
        self.assertEqual(result.action_items, [])
        self.assertEqual(result.risks, [])

    def test_missing_rationale_and_owner(self):
        text = "The team selected Cedar. The report must be submitted; no owner was named."
        result = extractor(draft(decisions=[decision(text)], action_items=[action(text, status="open")])).extract(chunk(text))
        self.assertIsNone(result.decisions[0].rationale)
        self.assertIsNone(result.decisions[0].decision_date)
        self.assertIsNone(result.action_items[0].owner)

    def test_unknown_status_and_risk_severity(self):
        text = "A delivery risk was recorded. A report was assigned, but its current state is not recorded."
        risk = RiskDraft(description="Delivery risk", severity="unknown", status="unknown", evidence_excerpts=[text])
        result = extractor(draft(action_items=[action(text)], risks=[risk])).extract(chunk(text))
        self.assertEqual(result.action_items[0].status, "unknown")
        self.assertEqual(result.risks[0].severity, "unknown")

    def test_fabricated_evidence_rejected_for_every_kind(self):
        text = "The team selected Cedar."
        for excerpts in ([], [""], [" "], ["Invented quote"], [text, "Invented quote"], ["x" * 601]):
            with self.subTest(excerpts=excerpts):
                output = draft(decisions=[decision(text, evidence_excerpts=excerpts)],
                               action_items=[action(text, evidence_excerpts=excerpts)],
                               risks=[RiskDraft(description=text, severity="unknown", status="unknown", evidence_excerpts=excerpts)])
                result = extractor(output).extract(chunk(text))
                self.assertEqual(len(result.rejected_items), 3)
                self.assertEqual((result.decisions, result.action_items, result.risks), ([], [], []))

    def test_exact_unicode_and_application_owned_provenance(self):
        text = "اختار أحمد المورد."
        output = draft(decisions=[decision(text, evidence_excerpts=["اختار احمد المورد."])])
        self.assertEqual(len(extractor(output).extract(chunk(text)).rejected_items), 1)
        output = draft(decisions=[decision(text)])
        engine = extractor(output)
        result = engine.extract(chunk(text)).decisions[0]
        reference = result.evidence_references[0]
        self.assertEqual((reference.source, reference.page, reference.document_id, reference.chunk_id),
                         ("meeting.md", 2, "document-1", "chunk-1"))
        self.assertEqual(result.id, engine.extract(chunk(text)).decisions[0].id)
        with self.assertRaises(ValidationError):
            DecisionDraft.model_validate({**output.decisions[0].model_dump(), "source": "fabricated.pdf"})

    def test_fabricated_owner_and_deadline_rejected(self):
        text = "Ahmed must send the plan."
        for item in (action(text, owner="Sara"), action(text, deadline_text="Sunday"),
                     action(text, deadline_text="2026-01-01")):
            result = extractor(draft(action_items=[item])).extract(chunk(text))
            self.assertFalse(result.action_items)
            self.assertEqual(len(result.rejected_items), 1)

    def test_explicit_date_parser_and_fabricated_date_rejection(self):
        for phrase, expected in (("3 سبتمبر 2026", date(2026, 9, 3)),
                                 ("٣ سبتمبر ٢٠٢٦", date(2026, 9, 3)),
                                 ("August 12, 2026", date(2026, 8, 12)),
                                 ("2026-08-12", date(2026, 8, 12)),
                                 ("قبل يوم الأحد", None), ("31 February 2026", None),
                                 ("12/08/2026", None), ("August 12", None)):
            self.assertEqual(parse_explicit_date(phrase), expected)
        text = "On 12 August 2026 the team selected Cedar."
        result = extractor(draft(decisions=[decision(text, decision_date_text="1208-12-08")])).extract(chunk(text))
        self.assertEqual(result.decisions, [])
        self.assertEqual(result.rejected_items[0].reason, "unsupported_date")

    def test_verified_header_date_attached_by_application(self):
        text = "3 سبتمبر 2026\nاتفق الفريق على تغيير المورد."
        output = draft(decisions=[decision("اتفق الفريق على تغيير المورد.", decision_date_text="3 سبتمبر 2026")])
        result = extractor(output).extract(chunk(text)).decisions[0]
        self.assertEqual(result.decision_date, date(2026, 9, 3))
        self.assertEqual(result.evidence_references[-1].excerpt, "3 سبتمبر 2026")

    def test_refusal_incomplete_and_missing_output(self):
        for status, output in (("incomplete", draft()), ("completed", None)):
            with self.assertRaises(ExtractionError):
                extractor(output, status=status).extract(chunk("Text"))

    def test_evidence_required_by_memory_models(self):
        with self.assertRaises(ValidationError):
            Decision(id="id", title="title", description="description", evidence_references=[])
        with self.assertRaises(ValidationError):
            EvidenceReference(document_id="id", chunk_id="id", source="file", excerpt=" ")


class MemoryStoreTests(unittest.TestCase):
    def test_roundtrip_and_tampering_rejection(self):
        source = chunk("اختار الفريق المورد.")
        memory = extract_memory([source], extractor(draft(decisions=[decision(source.text)])))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            save_memory(memory, path)
            self.assertEqual(load_memory(path), memory)
            original = path.read_text(encoding="utf-8")
            self.assertIn(source.text, original)
            for field, value in (("source", "fabricated"), ("page", 99), ("document_id", "fake"),
                                 ("chunk_id", "fake"), ("excerpt", "fake")):
                data = json.loads(original)
                data["decisions"][0]["evidence_references"][0][field] = value
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValidationError):
                    load_memory(path)

    def test_atomic_failure_and_replacement(self):
        source = chunk("Team selected Cedar.")
        memory = extract_memory([source], extractor(draft(decisions=[decision(source.text)])))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.json"
            save_memory(memory, path)
            original = path.read_bytes()
            with patch("athar.memory_store.os.replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError):
                    save_memory(memory, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            save_memory(memory, path)
            self.assertEqual(len(load_memory(path).decisions), 1)

    def test_cli_failure_preserves_store_and_sanitizes_errors(self):
        source = chunk("Team selected Cedar.")
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory) / "index.npz"
            output = Path(directory) / "memory.json"
            LocalVectorStore([source], np.array([[1, 0]]), model="test").save(index)
            engine = extractor(draft(decisions=[decision(source.text)]))
            with patch("scripts.extract_memory.MemoryExtractor", return_value=engine), contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(main(["--store", str(index), "--output", str(output)]), 0)
            self.assertIn("Documents processed: 1", stdout.getvalue())
            original = output.read_bytes()
            for error in (OpenAIError("synthetic-secret"), ExtractionError("synthetic-secret")):
                engine._client.responses.parse.side_effect = error
                with patch("scripts.extract_memory.MemoryExtractor", return_value=engine), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(main(["--store", str(index), "--output", str(output)]), 1)
                self.assertNotIn("synthetic-secret", stderr.getvalue())
                self.assertEqual(output.read_bytes(), original)

    def test_zero_objects_still_preserve_processed_chunks(self):
        source = chunk("Discussion only")
        memory = extract_memory([source], extractor(draft()))
        self.assertEqual(memory.source_chunks, [source])
        self.assertEqual(memory.decisions, [])


if __name__ == "__main__":
    unittest.main()
