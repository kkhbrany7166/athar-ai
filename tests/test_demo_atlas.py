"""Packaging tests run the real demo orchestration with mocked external model outputs."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from openai import OpenAIError

from athar.action_updates import ActionMatcher, UpdateDraft, UpdateMatch
from athar.extraction import ActionDraft, DecisionDraft, ExtractionDraft, ground_extraction
from athar.reranking import CandidateReranker, CandidateJudgment, QueryUnderstanding, RerankOutput
from scripts.demo_atlas import EXAMPLES_DIR, main, run_demo


class AtlasDemoTests(unittest.TestCase):
    def test_complete_demo_uses_examples_and_holds_back_later_evidence(self):
        extracted_sources = []
        extractor = Mock()
        def extract(chunk):
            extracted_sources.append(chunk.source)
            meeting = chunk.source == 'meeting_03_ar.md'
            decision = DecisionDraft(title='Replace integration company' if meeting else 'Initial selection',
                description=chunk.text, rationale=None, participants=[],
                decision_date_text='3 سبتمبر 2026' if meeting else '12 August 2026',
                evidence_excerpts=[chunk.text])
            actions = [ActionDraft(description='طلب خطة التنفيذ المحدثة',owner='أحمد',deadline_text='قبل يوم الأحد',
                       status='unknown',evidence_excerpts=[chunk.text])] if meeting else []
            return ground_extraction(ExtractionDraft(decisions=[decision],action_items=actions,risks=[]),chunk)
        extractor.extract.side_effect = extract
        extractor.model = 'mock'
        embedder = Mock(model='test')
        embedder.embed.side_effect = lambda texts: np.ones((len(texts), 2))
        rerank_client = Mock()
        def relevance(**kwargs):
            payload = json.loads(kwargs['input'][1]['content'])
            judgments = [CandidateJudgment(candidate_id=c['candidate_id'],relevance=4 if
                c['result_type']=='decision' and 'Replace integration company' in c['text'] else 2)
                for c in payload['candidates']]
            return SimpleNamespace(status='completed',output_parsed=RerankOutput(
                query=QueryUnderstanding(intent='decision_reason',entities=[],asks_change=True,asks_why=True,temporal_language=[]),
                judgments=judgments))
        rerank_client.responses.parse.side_effect = relevance
        matcher_client = Mock()
        def match(**kwargs):
            payload = json.loads(kwargs['input'][1]['content'])
            self.assertIn('7 سبتمبر 2026',payload['new_text'])
            excerpt = payload['new_text'].split('\n\n')[1]
            return SimpleNamespace(status='completed',output_parsed=UpdateMatch(match=UpdateDraft(
                candidate_id='a1',update_type='completed',description='Plan received',observed_date_text='7 سبتمبر 2026',
                previous_owner=None,new_owner=None,evidence_excerpts=[excerpt])))
        matcher_client.responses.parse.side_effect = match
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with patch('scripts.demo_atlas.OpenAIEmbedder',return_value=embedder), patch('scripts.demo_atlas.MemoryExtractor',return_value=extractor), patch('athar.reranking.CandidateReranker',return_value=CandidateReranker(client=rerank_client)), patch('scripts.demo_atlas.ActionMatcher',return_value=ActionMatcher(client=matcher_client)), contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(run_demo(target))
            self.assertEqual(extracted_sources,['procurement_plan.md','meeting_03_ar.md'])
            report = json.loads((target/'demo_report.json').read_text())
            self.assertTrue(all(report['checks'].values()))
            self.assertEqual(report['transitions'][0]['before']['action'],report['transitions'][0]['after']['action'])
            self.assertEqual(report['transitions'][0]['after']['state'],'completed')
            self.assertEqual(len(json.loads((target/'actions_before.json').read_text())['updates']),0)

    def test_missing_key_fails_without_creating_runtime_data(self):
        with patch.dict('os.environ',{},clear=True), patch('scripts.demo_atlas.tempfile.mkdtemp') as create, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(main([]),1)
        create.assert_not_called()
        self.assertIn('OPENAI_API_KEY',output.getvalue())

    def test_provider_error_is_not_echoed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-placeholder'}), patch('scripts.demo_atlas.PROJECT_ROOT',Path(directory)), patch('scripts.demo_atlas.run_demo',side_effect=OpenAIError('synthetic-private-details')), contextlib.redirect_stderr(io.StringIO()) as error, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([]),1)
            self.assertNotIn('synthetic-private-details',error.getvalue())

    def test_versioned_example_contains_only_three_story_documents_and_readme(self):
        self.assertEqual({p.name for p in EXAMPLES_DIR.iterdir()},
                         {'procurement_plan.md','meeting_03_ar.md','meeting_07_ar.md','README.md'})
