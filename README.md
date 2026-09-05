# Athar AI — أثر

**Bilingual organizational decision intelligence for Arabic-English teams.**

Athar's long-term purpose is organizational decision memory: preserving what a team decided, why, who participated or owns the follow-up, what remains unresolved, and the evidence behind each fact.

Phase 1 establishes bilingual document ingestion and multilingual semantic retrieval. Phase 2 extracts evidence-backed decisions, action items, and risks into local organizational memory. The query command still returns raw evidence chunks; it does not answer questions or search the structured memory.

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
- Ingest/query/extraction CLIs, offline tests, and a small, explicitly synthetic bilingual retrieval dataset.

## Planned

```text
documents + meeting transcripts
→ structured organizational memory
→ decisions / actions / risks
→ evidence-grounded question answering
→ open-loop tracking
→ contradiction detection
```

Decision-aware retrieval, open-loop tracking, contradiction detection, agentic question answering, and UI are planned. Audio transcription and cross-document entity resolution are also future work; plain-text meeting notes already use the document pipeline.

**Future example**

Question: **"ليش غيرنا المورد؟"**

Expected future behavior: Athar identifies the relevant decision, rationale, and supporting meeting/document evidence. Today, extraction saves the decision and rationale separately, while the query CLI retrieves and prints potentially relevant document chunks. Connecting these paths is planned.

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
```

Tests cover source identity, actual PDF text extraction and page numbering, Unicode chunk coverage, batching and response ordering, request bounds, vector validation, deterministic cosine ranking, persistence, failed-write recovery, models, and CLI integration with mocked embeddings. Extraction tests use mocked structured responses for Arabic/English decisions, Arabic actions, code-switching, discussion without decisions, missing fields, fabricated evidence and people, refusal/incomplete output, JSON roundtrips, and failure preservation. Mocked outputs verify application contracts, not model judgment or semantic quality. No live API calls are part of the normal test suite.

`evals/retrieval_dataset.jsonl` contains seven synthetic queries with expected source files and evidence spans. The corresponding corpus lives in `evals/fixtures/`. To inspect live retrieval without mixing fixtures into your real index:

```bash
python -m scripts.ingest --documents evals/fixtures --store data/processed/eval_store.npz
python -m scripts.query "ليش غيرنا المورد؟" --top-k 1 --store data/processed/eval_store.npz
python -m scripts.query "What did Ahmed promise to deliver and by when?" --top-k 1 --store data/processed/eval_store.npz
```

For each dataset row, compare the retrieved `source` and text with `expected_sources` and `expected_evidence`. The dataset is a manual smoke-test seed, not a benchmark or an automated evaluation runner. No semantic quality scores are claimed. Live document embeddings, query embeddings, and bilingual semantic checks require a valid API key and available API quota.

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

## Boundaries and data handling

- Embedding calls send document chunks and queries to OpenAI; extraction sends chunk text. Vectors, chunk text, and organizational memory are stored locally without encryption.
- Exact quote matching proves that an excerpt occurs in the chunk; it does **not** prove that every generated claim follows from that excerpt. Decisions, rationale, dates, status, and risk classification still need human review. Chunk-local extraction can miss context and cannot reconcile later updates, contradictions, or aliases.
- Prompt instructions treat source text as untrusted data, but this is not a guarantee against prompt injection or model mistakes.
- `.env`, local documents, processed data, NumPy artifacts, virtual environments, and common editor/OS files are ignored by Git. Only synthetic fixtures are intended for version control.
- PDF extraction depends on the document's text layer. Blank/image-only pages are warned about and skipped; OCR, layout reconstruction, and encrypted PDFs are unsupported. Arabic PDF reading order depends on the source encoding and should be inspected.
- Exact NumPy search loads the entire corpus into memory. This is a small-corpus foundation, without hosted vector databases, reranking, access control, or production concurrency guarantees.
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
│   └── memory_store.py
├── scripts/
│   ├── __init__.py
│   ├── ingest.py
│   ├── query.py
│   └── extract_memory.py
├── evals/
│   ├── retrieval_dataset.jsonl
│   └── fixtures/
│       ├── supplier.md
│       ├── launch.txt
│       └── actions_ar.md
└── tests/
    ├── __init__.py
    ├── test_pipeline.py
    ├── test_config.py
    └── test_extraction.py
```
