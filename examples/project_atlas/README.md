# Project Atlas: a synthetic organizational history

All organizations, people, and events in these documents are fictional demonstration data. The example mixes English procurement evidence with Arabic meeting notes and English technical terminology.

| Source | Date | Event |
| --- | --- | --- |
| `procurement_plan.md` | 2026-08-12 | Falcon Systems selected based on its integration delivery commitment and experience; schedule reliability matters. |
| `meeting_03_ar.md` | 2026-09-03 | Delivery delay threatens launch. The team replaces Falcon with Nova Technologies and assigns أحمد to request an updated implementation plan. |
| `meeting_07_ar.md` | 2026-09-07 | أحمد has contacted Nova and received the plan, completing that commitment. Unrelated discussion supplies noise. |

From the repository root, after installing dependencies and configuring your local `.env`:

```bash
python -m scripts.demo_atlas
```

The demo explicitly reads these three documents; this README is not ingested. It indexes and extracts the first two before introducing the third as later action-update evidence. This preserves the unresolved-before/completed-after demonstration without fabricating state.

OpenAI access is required for embeddings, extraction, reranking, and update matching. Generated outputs are written to a fresh ignored `data/processed/atlas-demo-*` directory per run. No precomputed memory, vectors, or expected final model outputs are bundled here. Model results can vary; the demo prints what happened and exits nonzero if the key expectations are not met.
