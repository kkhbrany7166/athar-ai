export type Evidence = {
  document_id: string;
  chunk_id: string;
  source: string;
  page: number | null;
  excerpt: string;
};
export type Document = {
  id: string;
  filename: string;
  size: number;
  status: string;
  kind: string;
};
export type Project = {
  id: string;
  name: string;
  synthetic: boolean;
  status: string;
  stage: string;
  error: string | null;
  documents: Document[];
  snapshot_id: string | null;
};
export type Decision = {
  decision_id: string;
  title: string;
  description: string;
  rationale: string | null;
  date: string | null;
  date_status: string;
  evidence_references: Evidence[];
};
export type MemoryItem = {
  id: string;
  title?: string;
  description: string;
  rationale?: string | null;
  decision_date?: string | null;
  severity?: string;
  status?: string;
  evidence_references: Evidence[];
};
export type Action = {
  action: MemoryItem & { owner: string | null; deadline_text: string | null };
  owner: string | null;
  state: string;
  unresolved: boolean;
  assignment_date: string | null;
  latest_known_date: string | null;
  warnings: string[];
  history: {
    event_id: string;
    event_type: string;
    date: string | null;
    description: string;
    applied: boolean;
    evidence_references: Evidence[];
  }[];
};
export type Ranked = {
  candidate_id: string;
  base_rank: number;
  reranked_rank: number;
  base_score: number;
  relevance: number | null;
  result: {
    result_type: "decision" | "action_item" | "risk" | "document";
    text: string;
    item: MemoryItem | null;
    item_id: string | null;
    evidence_references: Evidence[];
    cosine_score: number;
  };
};
export type Search = {
  results: Ranked[];
  timeline: Decision[];
  rerank_status: string;
  rerank_model_calls: number;
};
export type Memory = {
  timeline: Decision[];
  risks: MemoryItem[];
  rejected_records?: number;
};
export type Selection = {
  title: string;
  evidence: Evidence[];
  recordType: "decision" | "action_item" | "risk" | "document";
};
