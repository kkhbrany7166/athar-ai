# Athar AI — أثر

**Bilingual organizational decision intelligence for Arabic-English teams.**

Athar's long-term purpose is organizational decision memory: preserving what a team decided, why, who participated or owns the follow-up, what remains unresolved, and the evidence behind each fact.

Phase 1 establishes bilingual document ingestion and multilingual semantic retrieval. Phase 2 extracts evidence-backed decisions, action items, and risks into local organizational memory. Phase 3 adds cached organizational-memory embeddings, hybrid memory/document ranking, and a basic decision timeline. The original query command remains raw-only; the new search command returns both domains. Phase 3.1 adds event-aware reranking over a bounded hybrid candidate set. None of these commands generates answers.

## Implemented now

- Recursive ingestion of UTF-8 `.txt`, `.md`, and text-based `.pdf` files.
- Source-relative filenames, content-versioned document IDs, and one-based PDF page numbers.
- Overlapping, whitespace-aware chunks with reproducible IDs and exact character offsets into extracted page text.
- Batched `text-embedding-3-small` requests through the official OpenAI Python SDK; Arabic, English, and mixed text use the same path.
- Local NumPy cosine search, returning typed evidence chunks and similarity scores.
- Atomic persistence of vectors and JSON chunk metadata in one compressed `.npz` archive, loaded without pickle.
- Structured decision/action/risk extraction from Arabic, English, and mixed-language chunks using the official OpenAI SDK and Pydantic structured outputs.
- Exact evidence excerpt validation, application-owned source metadata, and required citations on every memory object.
- Persistent organizational memory in an atomic, readable JSON snapshot with input chunks, extraction model, prompt version, timestamp, and rejection diagnostics.
- Searchable decisions, action items, and risks with locally cached `text-embedding-3-small` vectors.
- Hybrid decision-aware retrieval with explicit result types, original evidence references, and inspectable ranking scores.
- Basic chronological timelines of retrieved decisions using source-verified dates.
- Two-stage organizational retrieval: hybrid candidates followed by one structured query-understanding/relevance call, with baseline fallback and rank comparisons.
- Ingest/query/extraction/search CLIs, offline tests, and small retrieval evaluation datasets.

## Planned

```text
documents + meeting transcripts
→ structured organizational memory
→ decisions / actions / risks
→ evidence-grounded question answering
→ open-loop tracking
→ contradiction detection
```

Open-loop monitoring, contradiction detection, agentic question answering, and UI remain planned. Audio transcription and cross-document entity resolution are also future work; plain-text meeting notes already use the document pipeline.

**Future example**

Question: **"ليش غيرنا المورد؟"**

Expected future behavior: Athar identifies the relevant decision, rationale, and supporting meeting/document evidence. Today, search returns structured decisions with their stored rationale and evidence alongside raw document chunks. A conversational, evidence-grounded answer remains future work.

## Setup

Requires Python **3.11+**. Run commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally and replace its placeholder with your OpenAI API key. All CLIs automatically load this project's `.env` through `athar/config.py`, using an explicit path derived from that module's location. No manual export or implicit `.env` discovery is needed. Existing process environment variables take precedence over `.env` values.

The SDK is initialized only when embedding or extraction is requested. CLI help, imports, ingestion/chunking functions, and offline tests need no key. A missing `.env` is allowed when credentials are supplied through the environment.

## Ingest and query

Place documents under `data/documents/`, including subdirectories if useful:

```bash
python -m scripts.ingest
python -m scripts.query "ليش تأجل المشروع؟"
python -m scripts.query "Why was the supplier changed?" --top-k 5
```

The query CLI prints source, page where applicable, document/chunk IDs, character offsets, text, and cosine score. Scores measure vector similarity; they are not probabilities or validated confidence values. Search always returns up to `top_k` neighbors, including potentially irrelevant results; there is no relevance threshold or abstention logic yet.

For alternate paths:

```bash
python -m scripts.ingest --documents /path/to/documents --store /path/to/index.npz
python -m scripts.query "What was decided?" --store /path/to/index.npz
```

Each successful ingestion **rebuilds and replaces** the entire index, avoiding duplicate accumulation and removing deleted sources when other extractable sources remain. Empty input exits with a message and leaves the old index unchanged. Parsing, embedding, or save failures before replacement also preserve the previous index. Re-ingestion embeds all chunks again; incremental updates and caching are not implemented. Use a single ingest process at a time.

## Extract organizational memory

After ingestion, run:

```bash
python -m scripts.extract_memory
```

This reads the **already-ingested chunks** from `data/processed/vector_store.npz`, makes one structured extraction request per chunk, validates evidence, and writes `data/processed/organizational_memory.json`. It does not re-embed documents. Re-ingest first if source files changed.

```bash
python -m scripts.extract_memory --store /path/to/index.npz --output /path/to/memory.json
```

The default extraction model is `gpt-4.1-mini-2025-04-14`; `--model` accepts another model supporting the same structured-output request. The implementation uses `client.responses.parse(..., text_format=ExtractionDraft)` as described in the [official OpenAI structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs). Model access and API quota are required. Requests use `store=False` and do not include tools.

The prompt distinguishes decisions from discussion and assigned actions from potential tasks. Missing rationale, owner, and dates remain null; participants stay empty if not explicit. Actions are open only when the source describes an unresolved commitment; otherwise their status may be unknown. The model copies `decision_date_text` and `deadline_text` verbatim; application code parses calendar dates. Supported forms are ISO `YYYY-MM-DD`, day + full English/Arabic month + year, and English month + day + year. Relative deadlines, unsupported formats/calendars, and ambiguous numeric dates retain their text with a null calendar date; no year or weekday is guessed. Risk severity defaults to unknown unless the model finds explicit severity or a clearly described impact it can conservatively classify.

The model generates fact fields and quotes only. Application code assigns record IDs and all document/chunk/source/page fields. Every saved item requires at least one nonblank exact evidence excerpt of at most 600 characters. If **any** excerpt is absent, altered, or invalid, the whole item is rejected. Explicit people and date/deadline phrases must also occur in the quoted evidence. If a copied decision date is present in the source but missing from the model's quotes, application code adds that exact phrase as a verified reference. A date phrase absent from the source causes rejection. Rejections are counted by the CLI and recorded by chunk, item kind/index, and reason in JSON.

A successful run replaces the full memory snapshot, including when no facts are extracted. It does not append duplicates across runs. Identical records within a chunk are deduplicated, but overlapping chunks may still yield duplicate facts. IDs are hashes of chunk identity and extracted content, so changed model wording can change IDs. There is no incremental extraction or cross-chunk merging.

API failures, refusals, incomplete responses, malformed output, or write failures abort the run before replacement, preserving the previous memory file. Items rejected by grounding checks are excluded while other valid items are saved. CLI errors do not echo API error bodies or model validation payloads. Run one extraction process at a time.

To inspect the saved snapshot offline:

```python
from athar.config import MEMORY_PATH
from athar.memory_store import load_memory

memory = load_memory(MEMORY_PATH)
for decision in memory.decisions:
    print(decision.title, decision.rationale)
    for evidence in decision.evidence_references:
        print(evidence.source, evidence.page, evidence.excerpt)
```

Loading and saving revalidate references against the included input chunks. `Decision.decision_date` replaces the Phase 1 schema's `date` field (the legacy name is accepted on input). Source-only chunk metadata remains compatible with Phase 1 indexes. Memory records now require evidence with excerpts; previously hand-built evidence-free model instances must supply it.

## Search organizational memory and raw evidence

```bash
python -m scripts.search_memory "Why did the team replace Falcon Systems?"
python -m scripts.search_memory "ليش تم اختيار Falcon Systems في البداية؟"
python -m scripts.search_memory "What happened with the integration vendor?" --timeline
python -m scripts.search_memory "وش صار على Falcon API integration والvendor الجديد؟"
```

The motivating Phase 1 failure was an English replacement question ranking the original English procurement document above the later Arabic replacement meeting. Structured memory makes individual decisions, rationale, assigned owners, and risks explicit search candidates instead of burying them in a document. It improves access to organizational facts, but does not eliminate embedding ambiguity or language bias.

The first stage of the search command reads the existing raw index and memory JSON. It embeds concise labeled fields: decision title/description/rationale/participants/date phrase, action description/owner/deadline/status, and risk description/severity/status. IDs, filenames, and repeated evidence excerpts are excluded from embedding text. Unknown fields are omitted. The source-language fields are not translated or expanded using another LLM.

`data/processed/memory_vectors.npz` stores the memory vectors, embedding model, ordered item IDs, representation version, and a content/provenance fingerprint. Missing, changed, incompatible, or corrupt caches are rebuilt atomically. An unchanged snapshot reuses its cache, even if only the extraction timestamp changes; each query still requires one query embedding. A changed snapshot rebuilds all memory vectors rather than only changed rows. No memory extraction runs during search.

Use `--store`, `--memory`, and `--cache` to select alternate paths. Cache files must differ from input files. The raw index's embedding model is used in both domains and vector dimensions must match. If a memory source chunk differs from or is absent in the raw index, search refuses the stale snapshot; run `python -m scripts.extract_memory` again. Newly added raw chunks without memory can still be searched. Missing or empty memory falls back to raw evidence. Invalid memory JSON fails validation rather than silently disappearing.

### First-stage ranking contract

Both domains use cosine similarity with the same embedding model. For the current defaults:

```text
memory eligible when cosine >= 0.25
memory ranking score = cosine + 0.08
document ranking score = cosine
```

Eligible memory and raw documents compete in a single descending ranking. There is no per-domain min/max normalization, keyword/entity rule, recency boost, or mandatory domain quota. The bonus is a small explicit prior for extracted organizational facts, not a learned calibration. Adjust it with `--memory-bonus`; adjust the gate with `--memory-min-cosine`. A zero bonus provides an ablation. Ties use cosine, result type, then stable ID. Defaults are provisional, not globally optimal or benchmark-tuned parameters.

The CLI prints `DECISION`, `ACTION_ITEM`, `RISK`, or `DOCUMENT` headings in final rank order, with relevance, base rank, base score, and original cosine. Structured entries include their ID and all evidence references. Raw entries retain full text and citation identity; their short reference excerpt is a locator, not an extracted claim. Python results also retain the original structured object or chunk, including raw offsets. Scores are not probabilities and adjusted scores can exceed 1. Weak memory is gated out, but raw neighbors are still returned even for an unrelated question; this is fallback, not reliable abstention.

### Two-stage organizational retrieval

By default, `scripts.search_memory` now reranks the top **8** hybrid candidates (at most **20**) before returning the requested top-K (default 5). The unchanged memory bonus and cosine gate still govern candidate generation. They do not get added to model relevance judgments.

One `gpt-4.1-mini-2025-04-14` structured-output call combines query understanding with candidate relevance judgments. Query attributes include intent, exact referenced entities, change/why flags, and explicit temporal phrases. Entities and temporal phrases absent from the original query are discarded. Intent and flags remain fallible model interpretations.

The model rates how directly each candidate addresses the requested event, distinguishing initial choices from later changes, reasons from mere entity mentions, assignments from background, and history from a specific event. It receives text, result type, and supporting excerpts, without base scores. It returns only query attributes and candidate IDs with ordinal relevance: 4 direct, 3 substantially relevant but incomplete, 2 background, 1 weak, 0 irrelevant. It never supplies replacement candidate content or an answer.

Application code maps allowed IDs back to trusted objects. Results sort by relevance, then prefer a matching structured type **only among direct (4) matches** for that intent, then preserve baseline order for ties. A directly answering document beats a background decision. There is no global decision-first rule or entity-specific keyword list. Low-rated candidates remain available at lower ranks; reranking is not an abstention system.

Unknown candidate IDs are discarded. Missing or duplicate valid IDs, refusal, incomplete/schema-invalid output, API errors, or oversized payloads preserve the complete baseline order. Errors are summarized without provider error bodies or model internals. Reranking has a 45-second timeout and no SDK retries. The candidate payload is capped at 120,000 UTF-8 bytes; oversized inputs fall back without truncating evidence.

```bash
# Baseline ablation: no reranking call
python -m scripts.search_memory "Why did the team replace Falcon Systems?" --no-rerank

# Save both ranks and scores for every candidate, including those outside output top-K
python -m scripts.search_memory "What happened with the integration vendor?" --candidate-count 8 --json
```

With a warm memory-vector cache, each normal query makes **one embedding request plus one structured reranking request**. Query understanding is included in that reranking call, not a separate request. Missing/stale memory vectors require additional batched embedding requests. Baseline mode makes no reranking call. There is no rerank-result cache, so repeating a query makes another model request. JSON reports attempted reranking API calls, status, model/prompt version, first-stage configuration, complete candidate base/reranked ranks, `base_score`, ordinal relevance, original objects, and the selected timeline.

The Python baseline API remains `athar.memory_retrieval.search_memory`. The two-stage API is:

```python
from athar.reranking import two_stage_search

response = two_stage_search("What happened with the integration vendor?")
for row in response.results:
    print(row.base_rank, row.reranked_rank, row.base_score, row.relevance)
    print(row.result.text)
```

The reranker cannot recover a relevant item missing from stage one's candidate pool. Latency, query-intent mistakes, prompt sensitivity, candidate-order bias, relevance ties, and duplicate memory/document hits remain weaknesses. This is a small tested refinement, not production-grade ranking or a measured general improvement.

### Decision chronology

`--timeline` orders only decisions in the returned top-K results, oldest first. The date phrase must occur in source-validated evidence and parse to the stored date. Unknown or unverified dates remain null and appear last, labeled accordingly. The latest known date among retrieved decisions does not identify the correct, active, or superseding decision. The timeline neither discovers relationships nor retrieves missing history; increase `--top-k` to inspect more candidates.

`athar.timeline.decision_timeline(decisions, source_chunks=chunks)` also supports explicitly supplied related decisions. Entries preserve IDs, title, description, rationale, verified date, date status, and evidence. Duplicate IDs appear once in the timeline. Selection and replacement are never merged just because they name the same vendor. Broader cross-chunk or semantic deduplication remains planned; extraction's existing exact in-chunk deduplication is unchanged.

```python
from athar.memory_retrieval import search_memory

response = search_memory("What happened with the integration vendor?", top_k=5)
for result in response.results:
    print(result.result_type, result.score, result.sources)
for entry in response.timeline:
    print(entry.date, entry.title)
```

## Python interface

```python
from athar.retrieval import retrieve_evidence

for evidence in retrieve_evidence("وش الأشياء اللي أحمد وعد يسويها؟", top_k=5):
    print(evidence.chunk.source, evidence.chunk.page, evidence.score)
    print(evidence.chunk.text)
```

Defaults live in `athar/config.py`. Query embeddings use the model recorded in the index; an explicitly injected embedder must match it.

## Evidence design

A document ID is a SHA-256 hash of its relative source path and original bytes. An unchanged file at the same relative path retains its ID; modifying or moving it produces a new ID. A chunk ID incorporates the document ID, page, offsets, and text.

PDF chunks stay within a page. Plain text and Markdown use `page=None`. Offsets are zero-based Unicode character positions, with an exclusive end, into **extracted text**, not original PDF byte positions or visual coordinates. Preserve the original documents alongside the index for later review. Citations support provenance, not independent verification that a statement is true.

Chunks default to 1,200 characters with 200-character overlap. Splits prefer whitespace in the latter part of each window and fall back to a hard boundary for long unbroken text. No translation or language-specific preprocessing is applied.

Embedding requests contain multiple texts (32 by default). Per-input and per-request UTF-8 byte caps conservatively bound token usage without adding a tokenizer. Oversized queries are rejected before any request; shorten them. The SDK handles transient retries with a 60-second request timeout and two retries. See the [official OpenAI embeddings API reference](https://developers.openai.com/api/reference/resources/embeddings/methods/create) for the request contract.

## Verification and retrieval evaluation

Offline checks:

```bash
python -m unittest discover -v
python -m compileall -q athar scripts tests
python -m scripts.ingest --help
python -m scripts.query --help
python -m scripts.extract_memory --help
python -m scripts.search_memory --help
```

Tests cover source identity, actual PDF text extraction and page numbering, Unicode chunk coverage, batching and response ordering, request bounds, vector validation, deterministic cosine ranking, persistence, failed-write recovery, models, and CLI integration with mocked embeddings. Extraction tests use mocked structured responses for Arabic/English decisions, Arabic actions, code-switching, discussion without decisions, missing fields, fabricated evidence and people, refusal/incomplete output, JSON roundtrips, and failure preservation. Mocked outputs verify application contracts, not model judgment or semantic quality. Phase 3 tests add deterministic ranking, action/risk and language routing, cache persistence/invalidation, raw fallback, source consistency, and verified/unknown timeline dates. No live API calls are part of the normal test suite.

`evals/retrieval_dataset.jsonl` contains seven synthetic queries with expected source files and evidence spans. The corresponding corpus lives in `evals/fixtures/`. To inspect live retrieval without mixing fixtures into your real index:

```bash
python -m scripts.ingest --documents evals/fixtures --store data/processed/eval_store.npz
python -m scripts.query "ليش غيرنا المورد؟" --top-k 1 --store data/processed/eval_store.npz
python -m scripts.query "What did Ahmed promise to deliver and by when?" --top-k 1 --store data/processed/eval_store.npz
```

For each dataset row, compare the retrieved `source` and text with `expected_sources` and `expected_evidence`. The dataset is a manual smoke-test seed, not a benchmark or an automated evaluation runner. No semantic quality scores are claimed. Live document embeddings, query embeddings, and bilingual semantic checks require a valid API key and available API quota.

`evals/memory_retrieval_dataset.jsonl` contains 20 focused Atlas questions labeled for structured Recall@K, top-1 structured-memory accuracy, and cross-language slices. [Evaluation notes](evals/README.md) define matching and metrics. These are smoke-test labels, not a representative benchmark or an automated metric runner.

## Project Atlas live smoke test

A live Phase 2 run against the two existing ingested Atlas sample chunks produced:

```text
Documents processed: 2
Chunks processed: 2
Decisions extracted: 2
Action items extracted: 1
Risks extracted: 1
Items rejected by grounding checks: 0
```

The saved decisions describe the initial selection of Falcon Systems on 2026-08-12 and its replacement with Nova Technologies on 2026-09-03 because of delivery delay. The Arabic action is assigned to أحمد to contact Nova Technologies for an updated implementation plan, with the source deadline `قبل يوم الأحد` preserved and the calendar deadline null. The risk concerns delivery delay threatening launch; severity is unknown.

The final run conservatively returned the action's status as unknown despite the explicit assignment. Participant lists include reporting/contributing roles and should not be read as formal approver lists. Earlier development runs omitted the risk and generated incorrect normalized dates; the final implementation copies date phrases and parses supported formats in application code. This is a reviewed smoke test, not an accuracy benchmark; model output can vary between runs.

## Phase 3 baseline Atlas acceptance results (before reranking)

Live checks used the existing two-document/four-item memory snapshot, `text-embedding-3-small`, representation version 1, top-K 5, memory bonus 0.08, and memory cosine gate 0.25. The table reports adjusted scores from these runs, not a benchmark:

| Query | Top results in order |
| --- | --- |
| Why did the team replace Falcon Systems? | Initial-selection decision **0.6614**; replacement decision **0.5791**; procurement document **0.5484** |
| ليش تم اختيار Falcon Systems في البداية؟ | Initial-selection decision **0.5504**; replacement decision **0.4721**; launch-delay risk **0.4427** |
| What happened with the integration vendor? | Initial-selection decision **0.5650**; procurement document **0.4740**; replacement decision **0.4508** |
| وش صار على Falcon API integration والvendor الجديد؟ | Launch-delay risk **0.6048**; initial-selection decision **0.5313**; replacement decision **0.5157** |

In the Phase 3 baseline, the explicit replacement acceptance condition passed: its structured decision ranks above the original procurement document. **The baseline replacement decision is not top-1**: the initial-selection decision still wins that query. This is a remaining event/language discrimination weakness, not a fully corrected top-1 result. The mixed query similarly puts the risk before the replacement decision. No entity-specific rules were added.

Both related decisions appear in the history query's top five, with verified chronology: **2026-08-12 initial selection → 2026-09-03 replacement**. This says nothing about which decision is currently authoritative. Fixed bonus/gate values, field weighting, cross-language calibration, result diversity, and a separately evaluated reranker should be revisited on a larger labeled corpus. Memory and its source document can occupy multiple slots; semantic deduplication is intentionally deferred.

## Phase 3.1 live ranking acceptance

The four requested checks were run against the existing Atlas snapshot with the same first-stage defaults, candidate limit 8, output K=5, `gpt-4.1-mini-2025-04-14`, and reranking prompt version `event-reranking-v2`. Each completed with one reranking API call and no fallback:

| Query | Baseline first three | Reranked first three |
| --- | --- | --- |
| Why did the team replace Falcon Systems? | Initial selection; replacement; procurement document | **Replacement**; meeting document; launch-delay risk |
| ليش تم اختيار Falcon Systems في البداية؟ | Initial selection; replacement; launch-delay risk | **Initial selection**; procurement document; replacement (relevance 0) |
| What happened with the integration vendor? | Initial selection; procurement document; replacement | **Replacement**; meeting document; launch-delay risk; initial selection remains at rank 4 |
| وش صار على Falcon API integration والvendor الجديد؟ | Launch-delay risk; initial selection; replacement | **Replacement**; meeting document; launch-delay risk |

Replacement moved from base rank **2 to 1** in the key English query. The Arabic initial-selection question retained the correct top-1. The broad history question surfaced both decisions within top five and preserved the verified timeline **2026-08-12 → 2026-09-03**. The mixed query prioritized the later operational change. Baseline scores remain unchanged; ordinal relevance is reported separately.

Local comparison artifacts are `data/processed/rerank_acceptance_a.json` through `rerank_acceptance_d.json` (ignored by Git), including all candidate base/final ranks and trusted evidence. These are four live smoke tests, not a general accuracy measurement. Initial prompt testing still ranked the old selection first for the mixed question; clearer event/intent instructions corrected that run. Query-understanding attributes remain imperfect: the final mixed query was marked as asking why, and explicit initial/new temporal wording was sometimes omitted. Ranking success does not validate every query attribute or imply stable production performance.

## Boundaries and data handling

- Embedding calls send document chunks and queries to OpenAI; extraction sends chunk text; reranking sends the question and bounded candidate text/excerpts. Vectors, chunk text, and organizational memory are stored locally without encryption.
- Exact quote matching proves that an excerpt occurs in the chunk; it does **not** prove that every generated claim follows from that excerpt. Decisions, rationale, dates, status, and risk classification still need human review. Chunk-local extraction can miss context and cannot reconcile later updates, contradictions, or aliases.
- Prompt instructions treat source text as untrusted data, but this is not a guarantee against prompt injection or model mistakes.
- `.env`, local documents, processed data, NumPy artifacts, virtual environments, and common editor/OS files are ignored by Git. Only synthetic fixtures are intended for version control.
- PDF extraction depends on the document's text layer. Blank/image-only pages are warned about and skipped; OCR, layout reconstruction, and encrypted PDFs are unsupported. Arabic PDF reading order depends on the source encoding and should be inspected.
- Exact NumPy search loads the entire corpus into memory. This is a small-corpus foundation, without hosted vector databases, access control, or production concurrency guarantees.
- Requirements specify compatible dependency ranges, not a reproducible lockfile. Verification in the initial workspace used Python 3.14; the source uses Python 3.11-compatible syntax.

## Project layout

```text
athar-ai/
├── .gitignore
├── .env.example
├── README.md
├── requirements.txt
├── data/
│   ├── documents/.gitkeep
│   └── processed/.gitkeep
├── athar/
│   ├── __init__.py
│   ├── config.py
│   ├── models.py
│   ├── ingestion.py
│   ├── chunking.py
│   ├── embeddings.py
│   ├── vector_store.py
│   ├── retrieval.py
│   ├── extraction.py
│   ├── memory_store.py
│   ├── memory_index.py
│   ├── memory_retrieval.py
│   ├── timeline.py
│   └── reranking.py
├── scripts/
│   ├── __init__.py
│   ├── ingest.py
│   ├── query.py
│   ├── extract_memory.py
│   └── search_memory.py
├── evals/
│   ├── README.md
│   ├── retrieval_dataset.jsonl
│   ├── memory_retrieval_dataset.jsonl
│   └── fixtures/
│       ├── supplier.md
│       ├── launch.txt
│       └── actions_ar.md
└── tests/
    ├── __init__.py
    ├── test_pipeline.py
    ├── test_config.py
    ├── test_extraction.py
    ├── test_memory_retrieval.py
    └── test_reranking.py
```
