"""Mocked event judgments verify reranking contracts without live model calls."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from openai import OpenAIError

from athar.memory_index import memory_items
from athar.memory_retrieval import RankingConfig, SearchResponse, rank_results
from athar.reranking import (
    CandidateReranker, CandidateJudgment, QueryUnderstanding, RerankOutput,
    rerank_candidates, two_stage_search,
)
from athar.timeline import decision_timeline
from tests.test_memory_retrieval import fixture


def baseline():
    memory = fixture()
    items = memory_items(memory)
    scores = {"initial": .8, "replacement": .7, "action": .5, "risk": .4}
    results = rank_results(items, [scores[x.id] for x in items], memory.source_chunks,
                           [.72, .6, .3, .2], top_k=8)
    return SearchResponse(results=results, timeline=decision_timeline(memory.decisions, source_chunks=memory.source_chunks),
                          memory_available=True, ranking=RankingConfig())


def output(base, *, intent="decision_reason", best="replacement", history=False):
    return RerankOutput(query=QueryUnderstanding(intent=intent, entities=["Cedar"],
                        asks_change=True, asks_why=True, temporal_language=[]),
        judgments=[CandidateJudgment(candidate_id=f"c{i}", relevance=4 if result.item_id == best or (
            history and result.item_id == "initial") else 2)
            for i, result in enumerate(base.results, 1)])


def engine(parsed):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=parsed)
    return CandidateReranker(client=client)


class RerankingTests(unittest.TestCase):
    def test_replacement_selection_why_and_languages(self):
        base = baseline()
        for query, intent, best in (
            ("Why was Cedar replaced?", "decision_reason", "replacement"),
            ("Why was Cedar originally selected?", "decision_reason", "initial"),
            ("ليش استبدلوا Cedar؟", "decision_reason", "replacement"),
            ("وش صار مع Cedar والتغيير الجديد؟", "decision", "replacement"),
            ("What must Ahmed deliver?", "action", "action"),
            ("ما الخطر على الإطلاق؟", "risk", "risk"),
        ):
            with self.subTest(query=query):
                reranker = engine(output(base, intent=intent, best=best))
                response = rerank_candidates(query, base, reranker=reranker)
                self.assertEqual(response.results[0].result.item_id, best)
                self.assertEqual(response.rerank_status, "applied")
                self.assertEqual(response.rerank_model_calls, 1)
                row = response.results[0]
                self.assertEqual(row.result, base.results[row.base_rank - 1])
                self.assertEqual(row.base_score, row.result.score)
                self.assertEqual(row.reranked_rank, 1)
                reranker._client.responses.parse.assert_called_once()

    def test_history_preserves_both_events_and_verified_dates(self):
        base = baseline()
        result = rerank_candidates("What changed over time?", base,
            reranker=engine(output(base, intent="decision_history", history=True)))
        self.assertEqual({row.result.item_id for row in result.results[:2]}, {"initial", "replacement"})
        self.assertEqual([entry.date.isoformat() for entry in result.timeline], ["2026-08-12", "2026-09-03"])

    def test_document_direct_answer_beats_background_decision(self):
        base = baseline()
        parsed = output(base)
        index = next(i for i, item in enumerate(base.results, 1) if item.result_type == "document")
        parsed = parsed.model_copy(update={"judgments": [CandidateJudgment(candidate_id=f"c{i}", relevance=4 if i == index else 2)
            for i in range(1, len(base.results) + 1)]})
        result = rerank_candidates("Archive setting?", base, reranker=engine(parsed))
        self.assertEqual(result.results[0].result.result_type, "document")

    def test_structured_tie_preference_only_for_direct_matching_intent(self):
        base = baseline()
        parsed = output(base)
        parsed = parsed.model_copy(update={"judgments": [CandidateJudgment(candidate_id=f"c{i}", relevance=4)
            for i in range(1, len(base.results) + 1)]})
        result = rerank_candidates("Why change?", base, reranker=engine(parsed))
        self.assertTrue(all(row.result.result_type == "decision" for row in result.results[:2]))

    def test_api_refusal_and_malformed_output_fall_back(self):
        base = baseline()
        for mode in ("api", "refusal", "incomplete", "malformed"):
            reranker = engine(output(base))
            if mode == "api":
                reranker._client.responses.parse.side_effect = OpenAIError("synthetic-secret")
            elif mode == "refusal":
                reranker._client.responses.parse.return_value.output_parsed = None
            elif mode == "incomplete":
                reranker._client.responses.parse.return_value.status = "incomplete"
            else:
                reranker._client.responses.parse.return_value.output_parsed = {"secret": "synthetic-secret"}
            result = rerank_candidates("question", base, reranker=reranker)
            self.assertEqual(result.rerank_status, "fallback")
            self.assertEqual([row.result for row in result.results], base.results[:5])
            self.assertNotIn("synthetic-secret", result.model_dump_json())

    def test_invalid_ids_discarded_without_content_injection(self):
        base = baseline()
        parsed = output(base)
        parsed.judgments.append(CandidateJudgment(candidate_id="invented-id", relevance=4))
        result = rerank_candidates("Why change Cedar?", base, reranker=engine(parsed))
        self.assertEqual(result.discarded_judgments, 1)
        self.assertEqual(result.rerank_status, "applied")
        self.assertEqual(len(result.candidates), len(base.results))
        self.assertNotIn("invented-id", result.model_dump_json())

    def test_missing_duplicate_and_all_invalid_judgments_fall_back(self):
        base = baseline()
        parsed = output(base)
        for judgments in (parsed.judgments[:-1], parsed.judgments + [parsed.judgments[0]],
                          [CandidateJudgment(candidate_id="fake", relevance=4)]):
            result = rerank_candidates("question", base, reranker=engine(parsed.model_copy(update={"judgments": judgments})))
            self.assertEqual(result.rerank_status, "fallback")
            self.assertEqual([row.result for row in result.candidates], base.results)

    def test_query_entities_and_temporal_phrases_must_come_from_query(self):
        base = baseline()
        parsed = output(base)
        parsed = parsed.model_copy(update={"query": QueryUnderstanding(intent="decision_reason",
            entities=["Cedar", "Invented"], asks_change=False, asks_why=True, temporal_language=["originally", "yesterday"])})
        result = rerank_candidates("Why was Cedar originally selected?", base, reranker=engine(parsed))
        self.assertEqual(result.query_understanding.entities, ["Cedar"])
        self.assertEqual(result.query_understanding.temporal_language, ["originally"])

    def test_payload_limit_falls_back_without_model_call(self):
        base = baseline()
        oversized = base.model_copy(update={"results": [base.results[0].model_copy(update={"text": "x" * 120001})]})
        reranker = engine(output(base))
        result = rerank_candidates("question", oversized, reranker=reranker)
        self.assertEqual(result.rerank_status, "fallback")
        self.assertEqual(result.rerank_model_calls, 0)
        reranker._client.responses.parse.assert_not_called()

    def test_empty_candidates_need_no_reranking(self):
        base = baseline().model_copy(update={"results": [], "timeline": []})
        reranker = engine(output(base))
        result = rerank_candidates("question", base, reranker=reranker)
        self.assertEqual(result.results, [])
        self.assertEqual(result.rerank_model_calls, 0)
        reranker._client.responses.parse.assert_not_called()

    def test_disabled_has_no_model_call_and_preserves_scores(self):
        base = baseline()
        reranker = engine(output(base))
        result = rerank_candidates("question", base, enabled=False, reranker=reranker)
        reranker._client.responses.parse.assert_not_called()
        self.assertEqual(result.rerank_model_calls, 0)
        self.assertEqual([row.base_score for row in result.results], [item.score for item in base.results[:5]])

    def test_bounded_first_stage_and_payload_contract(self):
        base = baseline()
        reranker = engine(output(base))
        with patch("athar.reranking.search_memory", return_value=base) as search:
            result = two_stage_search("Why was Cedar replaced?", candidate_count=8, reranker=reranker)
        self.assertEqual(search.call_args.args, ("Why was Cedar replaced?",))
        self.assertEqual(search.call_args.kwargs["top_k"], 8)
        kwargs = reranker._client.responses.parse.call_args.kwargs
        self.assertIs(kwargs["text_format"], RerankOutput)
        self.assertFalse(kwargs["store"])
        payload = json.loads(kwargs["input"][1]["content"])
        self.assertEqual(len(payload["candidates"]), 8)
        self.assertNotIn("base_score", payload["candidates"][0])
        self.assertEqual(len(result.candidates), 8)
        self.assertEqual(len(result.results), 5)
        with self.assertRaises(ValueError):
            two_stage_search("question", candidate_count=21)
