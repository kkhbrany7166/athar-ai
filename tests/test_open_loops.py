"""Offline action lifecycle tests with mocked embedding and matching responses."""
import contextlib
from datetime import date
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from openai import OpenAIError
from pydantic import ValidationError

from athar.action_updates import (ActionLedger, ActionMatcher, UpdateDraft, UpdateMatch,
    evidence, ground_update, header_date, load_ledger, process_updates, save_ledger)
from athar.memory_store import OrganizationalMemory, save_memory
from athar.models import ActionItem, Chunk
from athar.open_loops import latest_action_state, list_actions, open_loops
from scripts import open_loops as cli
from scripts.update_actions import main as update_main


def source(text, ident="new"):
    return Chunk(document_id=ident, chunk_id=ident, source=ident+".md", page=None,
                 text=text, start_char=0, end_char=len(text))


def initial():
    chunk = source("# Meeting — 3 September 2026\nأحمد مكلف بطلب خطة التنفيذ من Cedar.", "original")
    action = ActionItem(id="commitment", description="طلب خطة التنفيذ من Cedar", owner="أحمد",
                        deadline_text="الأحد", evidence_references=[evidence(chunk, "أحمد مكلف بطلب خطة التنفيذ من Cedar.")])
    return ActionLedger(actions=[action], source_chunks=[chunk])


def draft(kind="completed", *, phrase="7 سبتمبر 2026", excerpt="أحمد استلم خطة التنفيذ من Cedar.", **updates):
    fields = dict(candidate_id="a1", update_type=kind, description=excerpt, observed_date_text=phrase,
                  previous_owner=None, new_owner=None, evidence_excerpts=[excerpt])
    fields.update(updates)
    return UpdateDraft(**fields)


def new_source():
    return source("# متابعة — 7 سبتمبر 2026\nأحمد استلم خطة التنفيذ من Cedar.\nناقشت المجموعة الألوان دون قرار.")


def mock_matcher(output):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=UpdateMatch(match=output))
    return ActionMatcher(client=client)


def mock_embedder():
    embedder = Mock(model="test")
    embedder.embed.side_effect = lambda texts: np.ones((len(texts), 2))
    return embedder


def ledger_with(kind, *, day="7 سبتمبر 2026", text="أحمد استلم خطة التنفيذ من Cedar.", **fields):
    ledger = initial()
    chunk = source(f"# {day or 'Follow-up'}\n{text}")
    update = ground_update(draft(kind, phrase=day, excerpt=text, **fields), chunk, ledger.actions, model="test")
    return ActionLedger(actions=ledger.actions, source_chunks=[*ledger.source_chunks, chunk], updates=[update])


class StateTests(unittest.TestCase):
    def test_no_evidence_remains_unresolved(self):
        ledger = initial()
        result = latest_action_state(ledger, "commitment")
        self.assertEqual(result.state, "unknown")
        self.assertTrue(result.unresolved)
        self.assertEqual(result.assignment_date, date(2026, 9, 3))
        self.assertEqual(result.action.deadline_text, "الأحد")
        self.assertEqual(len(open_loops(ledger)), 1)

    def test_progress_completion_blocked_and_cancelled(self):
        for kind, state, unresolved in (("progress","in_progress",True), ("completed","completed",False),
                                        ("blocked","blocked",True), ("cancelled","cancelled",False)):
            with self.subTest(kind=kind):
                ledger = ledger_with(kind)
                item = latest_action_state(ledger, "commitment")
                self.assertEqual(item.state, state)
                self.assertEqual(item.unresolved, unresolved)
                self.assertEqual(len(open_loops(ledger)), int(unresolved))
                self.assertEqual(list_actions(ledger, state=state)[0], item)

    def test_reassignment_and_owner_filtering(self):
        ledger = ledger_with("reassigned", text="فاطمة ستتولى متابعة الخطة من أحمد.", previous_owner="أحمد", new_owner="فاطمة")
        self.assertEqual(latest_action_state(ledger,"commitment").owner, "فاطمة")
        self.assertEqual(open_loops(ledger, owner="أحمد"), [])
        self.assertEqual(len(open_loops(ledger, owner="فاطمة")), 1)
        self.assertEqual(ledger.actions[0].owner, "أحمد")

    def test_undated_completion_does_not_override_known_history(self):
        result = latest_action_state(ledger_with("completed", day=None), "commitment")
        self.assertEqual(result.state, "unknown")
        self.assertIsNone(result.history[-1].date)
        self.assertFalse(result.history[-1].applied)
        self.assertTrue(result.warnings)

    def test_chronological_order_is_not_processing_order(self):
        ledger = ledger_with("completed")
        earlier = source("# 5 سبتمبر 2026\nأحمد تواصل مع Cedar وينتظر الخطة.", "progress")
        update = ground_update(draft("progress", phrase="5 سبتمبر 2026", excerpt="أحمد تواصل مع Cedar وينتظر الخطة."), earlier, ledger.actions, model="test")
        ledger = ledger.model_copy(update={"source_chunks":[*ledger.source_chunks,earlier], "updates":[*ledger.updates, update]})
        item = latest_action_state(ledger, "commitment")
        self.assertEqual(item.state, "completed")
        self.assertEqual([e.date for e in item.history], [date(2026,9,3),date(2026,9,5),date(2026,9,7)])

    def test_different_same_day_outcomes_are_not_arbitrarily_ordered(self):
        ledger = ledger_with("completed")
        chunk = source("# 7 سبتمبر 2026\nالخطة معلقة بسبب نقص البيانات.", "blocked")
        event = ground_update(draft("blocked", excerpt="الخطة معلقة بسبب نقص البيانات."),chunk,ledger.actions,model="test")
        ledger = ledger.model_copy(update={"source_chunks":[*ledger.source_chunks,chunk],"updates":[*ledger.updates,event]})
        result = latest_action_state(ledger,"commitment")
        self.assertEqual(result.state,"unknown")
        self.assertTrue(result.unresolved)

    def test_prior_or_same_assignment_date_does_not_change_state(self):
        for day in ("2 سبتمبر 2026", "3 سبتمبر 2026"):
            result = latest_action_state(ledger_with("completed",day=day),"commitment")
            self.assertEqual(result.state,"unknown")
            self.assertFalse(result.history[-1].applied)

    def test_header_date_does_not_infer_deadline(self):
        self.assertEqual(header_date(source("Meeting\nDeadline: 7 September 2026")),(None,None))
        self.assertEqual(header_date(source("# ٧ سبتمبر ٢٠٢٦"))[0],date(2026,9,7))
        self.assertEqual(header_date(source("# Deadline: 7 September 2026")),(None,None))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)/"cache.npz"

    def process(self, output, chunks=None, ledger=None):
        return process_updates(ledger or initial(), chunks or [new_source()], cache_path=self.cache,
                               embedder=mock_embedder(),matcher=mock_matcher(output))

    def test_valid_match_preserves_original_and_provenance(self):
        before = initial()
        report = self.process(draft())
        self.assertEqual(report.accepted,1)
        self.assertEqual(report.ledger.actions,before.actions)
        update = report.ledger.updates[0]
        self.assertEqual(update.action_id,"commitment")
        self.assertEqual(update.observed_date,date(2026,9,7))
        self.assertTrue(all(ref.source=="new.md" for ref in update.evidence_references))
        self.assertEqual(latest_action_state(report.ledger,"commitment").state,"completed")

    def test_creation_mention_and_unrelated_text_can_return_no_match(self):
        for text in ("أحمد سيطلب الخطة.", "أحمد ذكر Cedar.", "The projector is broken."):
            report = self.process(None, [source(text,text)])
            self.assertEqual(report.accepted,0)
            self.assertEqual(report.no_match,1)
            self.assertEqual(len(open_loops(report.ledger)),1)

    def test_invalid_candidate_and_fabricated_quotes_are_rejected(self):
        for output in (draft(candidate_id="fake-id"), draft(excerpt="Invented completion"),
                       draft(evidence_excerpts=[]), draft(evidence_excerpts=[" "]),
                       draft(phrase="3993-09-07")):
            with self.subTest(output=output):
                report = self.process(output)
                self.assertEqual(report.rejected,1)
                self.assertFalse(report.ledger.updates)

    def test_reassignment_requires_grounded_new_owner(self):
        for output in (draft("reassigned"),draft("reassigned",new_owner="Invented"),draft("completed",new_owner="أحمد")):
            self.assertEqual(self.process(output).rejected,1)

    def test_repeat_is_idempotent_with_zero_api_calls(self):
        first = self.process(draft())
        embedder, matcher = mock_embedder(), mock_matcher(draft())
        again = process_updates(first.ledger,[new_source()],cache_path=self.cache,embedder=embedder,matcher=matcher)
        self.assertEqual(len(again.ledger.updates),1)
        self.assertEqual(again.skipped,1)
        embedder.embed.assert_not_called()
        matcher._client.responses.parse.assert_not_called()
        self.assertEqual(first.ledger,again.ledger)

    def test_original_assignment_source_is_not_processed(self):
        ledger = initial()
        report = self.process(draft(),ledger.source_chunks,ledger)
        self.assertEqual(report.skipped,1)
        self.assertEqual(report.matching_calls,0)

    def test_candidate_generation_is_bounded(self):
        ledger = initial()
        ledger = ledger.model_copy(update={"actions":[ledger.actions[0].model_copy(update={"id":f"a{i}"}) for i in range(12)]})
        matcher=mock_matcher(None)
        process_updates(ledger,[new_source()],cache_path=self.cache,embedder=mock_embedder(),matcher=matcher,top_k=3)
        import json
        payload=json.loads(matcher._client.responses.parse.call_args.kwargs['input'][1]['content'])
        self.assertEqual(len(payload['candidates']),3)

    def test_schema_has_no_generated_provenance_or_final_state(self):
        import json
        schema=json.dumps(UpdateMatch.model_json_schema())
        for field in ('"document_id"','"chunk_id"','"source"','"page"','"state"'):
            self.assertNotIn(field,schema)

    def test_model_refusal_aborts_without_mutating_input(self):
        ledger = initial()
        before = ledger.model_dump_json()
        matcher = mock_matcher(draft())
        matcher._client.responses.parse.return_value.output_parsed = None
        with self.assertRaises(ValueError):
            process_updates(ledger, [new_source()], cache_path=self.cache,
                            embedder=mock_embedder(), matcher=matcher)
        self.assertEqual(ledger.model_dump_json(), before)

    def test_unknown_date_is_retained(self):
        report=self.process(draft(phrase=None))
        self.assertIsNone(report.ledger.updates[0].observed_date)
        self.assertEqual(latest_action_state(report.ledger,'commitment').state,'unknown')


class PersistenceTests(unittest.TestCase):
    def test_roundtrip_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.json'
            ledger=ledger_with('completed')
            save_ledger(ledger,path)
            self.assertEqual(load_ledger(path),ledger)
            corrupted=ledger.model_dump()
            corrupted['updates'][0]['evidence_references'][0]['source']='invented'
            with self.assertRaises(ValidationError):
                ActionLedger.model_validate(corrupted)

    def test_failed_atomic_write_preserves_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.json'
            save_ledger(initial(),path)
            before=path.read_bytes()
            with patch('athar.action_updates.os.replace',side_effect=OSError('disk failure')):
                with self.assertRaises(OSError):
                    save_ledger(ledger_with('completed'),path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(list(Path(directory).iterdir())),1)

    def test_cli_api_failure_preserves_history_and_hides_details(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            memory_path,updates_path=root/'memory.json',root/'updates.json'
            ledger=initial()
            save_memory(OrganizationalMemory(extraction_model='test',source_chunks=ledger.source_chunks,
                        action_items=ledger.actions),memory_path)
            save_ledger(ledger,updates_path)
            before=updates_path.read_bytes()
            with patch('scripts.update_actions.load_documents',return_value=[]), patch('scripts.update_actions.process_updates',side_effect=OpenAIError('synthetic-secret')), contextlib.redirect_stderr(io.StringIO()) as output:
                result=update_main(['--documents',str(root),'--memory',str(memory_path),'--updates',str(updates_path),'--cache',str(root/'cache.npz')])
            self.assertEqual(result,1)
            self.assertEqual(updates_path.read_bytes(),before)
            self.assertNotIn('synthetic-secret',output.getvalue())

    def test_history_cli_shows_both_evidence_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'updates.json'
            save_ledger(ledger_with('completed'),path)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['--updates',str(path),'--history','commitment']),0)
            for text in ('original.md','new.md','2026-09-03','2026-09-07','COMPLETED'):
                self.assertIn(text,output.getvalue())
