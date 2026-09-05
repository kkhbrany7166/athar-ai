# Athar AI — أثر

**Bilingual organizational decision intelligence for Arabic-English teams.**

Athar's long-term purpose is organizational decision memory: preserving what a team decided, why, who participated or owns the follow-up, what remains unresolved, and the evidence behind each fact.

Phase 1 establishes the document and retrieval foundation. It returns source evidence, without generating answers or extracting decisions.

## Implemented now

- Recursive ingestion of UTF-8 `.txt`, `.md`, and text-based `.pdf` files.
- Source-relative filenames, content-versioned document IDs, and one-based PDF page numbers.
- Overlapping, whitespace-aware chunks with reproducible IDs and exact character offsets into extracted page text.
- Batched `text-embedding-3-small` requests through the official OpenAI Python SDK; Arabic, English, and mixed text use the same path.
- Local NumPy cosine search, returning typed evidence chunks and similarity scores.
- Atomic persistence of vectors and JSON chunk metadata in one compressed `.npz` archive, loaded without pickle.
- Pydantic schemas for `Decision`, `ActionItem`, `Risk`, and `EvidenceReference`. These are definitions only; memory extraction and storage are not implemented.
- Ingest/query CLIs, offline tests, and a small, explicitly synthetic bilingual retrieval dataset.

## Planned

```text
documents + meeting transcripts
→ structured organizational memory
→ decisions / actions / risks
→ evidence-grounded question answering
→ open-loop tracking
→ contradiction detection
```

LLM extraction, answer generation, transcript/audio processing, unresolved commitment tracking, contradiction detection, UI, and agents are future work.

**Future example**

Question: **"ليش غيرنا المورد؟"**

Expected future behavior: Athar identifies the relevant decision, rationale, and supporting meeting/document evidence. Today, it only retrieves and prints potentially relevant evidence chunks.

## Setup

Requires Python **3.11+**. Run commands from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` locally and replace its placeholder with your OpenAI API key. Both CLIs automatically load this project's `.env` through `athar/config.py`, using an explicit path derived from that module's location. No manual export or implicit `.env` discovery is needed. Existing process environment variables take precedence over `.env` values.

The SDK is initialized only when embedding is requested. CLI help, imports, ingestion/chunking functions, and offline tests need no key. A missing `.env` is allowed when credentials are supplied through the environment.

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
```

Tests cover source identity, actual PDF text extraction and page numbering, Unicode chunk coverage, batching and response ordering, request bounds, vector validation, deterministic cosine ranking, persistence, failed-write recovery, models, and CLI integration with mocked embeddings. Mock vectors do **not** test semantic or cross-language retrieval quality.

`evals/retrieval_dataset.jsonl` contains seven synthetic queries with expected source files and evidence spans. The corresponding corpus lives in `evals/fixtures/`. To inspect live retrieval without mixing fixtures into your real index:

```bash
python -m scripts.ingest --documents evals/fixtures --store data/processed/eval_store.npz
python -m scripts.query "ليش غيرنا المورد؟" --top-k 1 --store data/processed/eval_store.npz
python -m scripts.query "What did Ahmed promise to deliver and by when?" --top-k 1 --store data/processed/eval_store.npz
```

For each dataset row, compare the retrieved `source` and text with `expected_sources` and `expected_evidence`. The dataset is a manual smoke-test seed, not a benchmark or an automated evaluation runner. No semantic quality scores are claimed. Live document embeddings, query embeddings, and bilingual semantic checks require a valid API key and available API quota.

## Boundaries and data handling

- Embedding calls send document chunks and queries to OpenAI. The vector index and chunk metadata are stored locally, without encryption.
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
│   └── retrieval.py
├── scripts/
│   ├── __init__.py
│   ├── ingest.py
│   └── query.py
├── evals/
│   ├── retrieval_dataset.jsonl
│   └── fixtures/
│       ├── supplier.md
│       ├── launch.txt
│       └── actions_ar.md
└── tests/
    ├── __init__.py
    └── test_pipeline.py
```
