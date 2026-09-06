# Phase 5: local web adapter

`Browser → Next.js / TypeScript → FastAPI → athar/`

The existing engine modules are unchanged. `server/services.py` owns project/file metadata and orchestrates `load_document`, `chunk_documents`, `extract_memory`, `process_updates`, `LocalVectorStore`, `two_stage_search`, `decision_timeline`, and `list_actions`. It does not reimplement extraction, ranking, evidence validation, or action state rules.

## API

Interactive Pydantic/OpenAPI documentation: http://localhost:8000/docs.

| Method | Endpoint | Contract |
| --- | --- | --- |
| GET | `/api/health` | Health and a boolean API-key presence flag; no credential value |
| GET | `/api/projects` | Local project metadata, newest first |
| POST | `/api/projects` | JSON `{ "name": "Project name" }`; generated project UUID |
| GET | `/api/projects/{project_id}` | Document statuses, processing stage, safe failure, snapshot identity |
| POST | `/api/projects/atlas/load` | Fresh synthetic Atlas workspace; background job; 202 |
| POST | `/api/documents/upload` | Multipart `project_id` and one `file`; uploaded metadata; 201 |
| POST | `/api/process` | JSON `{ "project_id": "UUID" }`; background processing; 202 |
| POST | `/api/search` | JSON `project_id`, `query` (1–2000 characters), optional `top_k` (1–8); engine reranked response |
| GET | `/api/decisions?project_id=UUID` | Verified/unknown timeline, risks, count of rejected proposed records |
| GET | `/api/actions?project_id=UUID` | Original actions, current states, owners, evidence and histories |
| GET | `/api/open-loops?project_id=UUID` | Unresolved subset; unknown states remain unresolved |
| GET | `/api/actions/{action_id}?project_id=UUID` | One action with complete history, scoped to the project |

The frontend shows engineering ranks and similarities only in optional retrieval details. An original action search result links to its latest state/history; it does not pretend the original extraction status is current.

## Persistence and processing

Each generated project UUID has an ignored directory under `data/processed/web/`:

- `project.json`: project metadata, document statuses, and active snapshot UUID.
- `uploads/<file-uuid>.<extension>`: uploaded bytes. The original filename is metadata and citation display text, not a filesystem destination.
- `snapshots/<snapshot-uuid>/`: raw vectors, validated memory, action ledger, and embedding caches.

A per-process lock prevents concurrent mutation of the same project's metadata. Processing marks pending documents before scheduling an in-process background job. New document chunks are extracted once; prior memory and original ActionItems are retained. New evidence is matched against the previous ledger before adding newly extracted actions. All sources enter the new search snapshot. Duplicate/edited uploads are distinct sources; semantic reconciliation is governed by the engine's existing limitations.

Atlas follows the same adapter pipeline but identifies the September 7 fixture as lifecycle follow-up evidence. That document is matched against the original commitments instead of being independently extracted as a new assignment. It remains available as raw searchable evidence. No fixture-specific decision/action outputs are created.

A complete snapshot is published by an atomic metadata rename only after all required engine operations succeed. Readers keep seeing the prior snapshot while processing, and a failed job removes its unpublished snapshot. Uploaded bytes and prior successful snapshots remain. Restarting the single server marks interrupted jobs failed/retryable. Runtime data persists across restarts; the browser remembers the selected project UUID locally.

Run only **one Python worker**. There is no distributed queue, durable job resumption, multi-process locking, authentication, or encrypted storage. Stop the server before manually deleting an unwanted workspace directory. The UI has no delete/rename/export or cancellation controls in Phase 5.

## UI boundaries

- Documents, Decisions/search, and Open Loops are local views on `/`, with shared project/evidence state; there are no shareable per-record URLs yet.
- English interface labels; Arabic, English, and mixed-language source records use `dir="auto"`. Evidence is plain text, never rendered as HTML or Markdown.
- Smaller screens place evidence below the main view and scroll/focus it on selection. Desktop uses a dedicated right panel.
- Dates are formatted in UTC to avoid day shifts. Unknown/unverified dates are never presented as verified.
- The UI displays verified structured records and literal excerpts, not generated answer prose. A count warns when source verification omitted proposed records; omission does not imply the source contained no relevant fact.
- The demo may vary between live runs. A first Phase 5 live run rejected one proposed decision for invalid evidence; a fresh run passed the complete timeline/search acceptance check. The adapter does not weaken verification to force a demo result.

No Phase 5 authentication, teams, database accounts, billing, cloud deployment, integrations, autonomous agents, contradiction detection, or transcription has been added.

## Verification result

Phase 5 passed 113 Python tests (91 original + 22 API), compile/import and Python 3.11 syntax checks, TypeScript checking, four formatting tests, six fully mocked Playwright UI tests, and a Next.js production build under Node 24.19.0. No ordinary test makes a real OpenAI call.

A fresh live browser Atlas run processed three documents, displayed both verified decision dates, ranked the replacement decision first for the English question, and showed Ahmed's same-ID assignment → completion history. English, Arabic, and mixed-language questions were exercised, and UI excerpts were compared exactly with each API response. The Arabic question returned a raw document first; ranked result types are not forced by the UI. Desktop and 390px mobile views were inspected, with no horizontal overflow or browser exceptions.

Screenshots and the real API report are local ignored artifacts in `data/processed/web-verification/`: `welcome.png`, `processing.png`, `decisions.png`, `search-evidence.png`, `action-history.png`, `documents.png`, `mobile.png`, `mobile-evidence.png`, and `live-report.json`. The application views are available at http://localhost:3000; API documentation at http://localhost:8000/docs.

The final hygiene check found no actual API-key value in reviewable source files or the browser build, no tracked uploads, and no changes to `athar/`. No commit was made.
