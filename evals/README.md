# Retrieval evaluation seeds

`retrieval_dataset.jsonl` is the Phase 1 synthetic fixture dataset. Its files are in `fixtures/`.

`memory_retrieval_dataset.jsonl` targets the existing local Project Atlas sample (`meeting_03_ar.md` and `procurement_plan.md`) and its Phase 2 organizational memory. It is 20 manually labeled focused questions, not a representative benchmark. The local corpus and generated indexes remain ignored by Git. To reproduce this dataset, use the same Atlas documents, ingest them, and extract memory before searching; another extraction may produce different items or quotes.

Each `expected_items` entry identifies a relevant structured fact by result type, source filename, and an exact substring of supporting evidence. This avoids dependence on model-generated titles and content-derived item IDs. A retrieved result matches only when its type matches and one of its evidence references has both the expected source and the expected `evidence_contains` substring. A raw document that mentions a decision does not count as retrieving that structured decision. Review labels if valid model quotes change enough to miss these substrings.

Future evaluation runners should use:

- **Recall@K:** number of distinct expected items matched in the first K hybrid results divided by the number of expected items. Match targets one-to-one with results, so duplicates cannot inflate recall. Average per-query recall for macro Recall@K.
- **Top-1 structured-memory accuracy:** fraction of queries for which the first overall hybrid result is structured and matches an expected item indexed in `expected_top1`. A raw result at rank 1 counts as a miss, even if a relevant decision appears later.
- **Cross-language retrieval:** report the same metrics separately for Arabic queries with English evidence, English queries with Arabic evidence, same-language queries, and mixed-language queries. Use the language labels, not guessed result language.

Always report K, corpus/snapshot identity, model, representation version, ranking configuration, number of queries, and per-query misses. The broad vendor-history question has two targets, specifically preserving initial selection and later replacement as separate decisions. Do not count chronological sorting as improved retrieval recall.

Normal offline tests use deterministic embeddings and include direct decisions, owner/action and risk queries, language routing, raw fallback, chronology, and cache lifecycle checks. They establish software behavior, not semantic accuracy. No live calls or fabricated aggregate scores are included here. An automated metric runner and a larger independently labeled corpus remain future work.

## Phase 3.1 comparisons

Run `python -m scripts.search_memory "QUERY" --json` to obtain the same candidate pool's base and reranked orders. Each candidate keeps `candidate_id`, `base_rank`, `reranked_rank`, `base_score`, relevance, and its original result with evidence. Sort `candidates` by `base_rank` for baseline metrics, or by `reranked_rank` for final metrics; apply the same K and labels to both. Do not count different candidate pools as a reranking-only improvement. Compare model/status and inspect fallback runs separately. A reranker cannot recover targets excluded by first-stage retrieval.

The 20 questions include event transitions, original selection, reasons, ownership/deadlines, risks, history, and cross-language or mixed-language phrasing. They are variations on a single small corpus, not 20 independent organizational scenarios. Reranker/query-understanding outputs are mocked in normal tests. Only the four requested live acceptance questions are used for the current manual check; no aggregate quality score is claimed.

## Phase 4 lifecycle fixture

`fixtures/atlas_followup/meeting_07_ar.md` is a deliberately synthetic later Atlas meeting, dated 7 September 2026. Process it with `scripts.update_actions --documents evals/fixtures/atlas_followup` against the existing Atlas organizational memory. The expected outcome is completion of the existing Ahmed/Nova plan-request action without changing its ID or assignment evidence. It contains unrelated discussion as noise. The fixture is a single manual acceptance scenario, not a lifecycle benchmark.
