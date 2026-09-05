import type { Action, Decision, Search, Selection } from "@/lib/types";
import { dateLabel, kindLabel, stateLabel } from "@/lib/format";
export function DecisionRecord({
  decision,
  select,
}: {
  decision: Decision;
  select: (s: Selection) => void;
}) {
  return (
    <article className="record">
      <div className="record-meta">
        <span className="badge decision">Decision</span>
        <span>{dateLabel(decision.date, decision.date_status)}</span>
      </div>
      <h2 dir="auto">{decision.title}</h2>
      <p dir="auto">{decision.description}</p>
      <div className="rationale">
        <span className="eyebrow">Why this decision</span>
        <p dir="auto">
          {decision.rationale || "No rationale established in the source."}
        </p>
      </div>
      <button
        className="evidence-button"
        onClick={() =>
          select({
            title: decision.title,
            evidence: decision.evidence_references,
          })
        }
      >
        Inspect evidence <span>↗</span>
      </button>
    </article>
  );
}
export function SearchResults({
  search,
  select,
  openAction,
}: {
  search: Search;
  select: (s: Selection) => void;
  openAction: (id: string) => void;
}) {
  const records = search.results.map((row, index) => {
    const result = row.result;
    const title =
      result.item?.title ||
      result.item?.description ||
      result.evidence_references[0]?.source ||
      "Document evidence";
    const timeline = search.timeline.find(
      (t) => t.decision_id === result.item_id,
    );
    return (
      <article
        className={`record search-record ${index === 0 ? "primary-result" : ""}`}
        key={row.candidate_id}
      >
        <div className="record-meta">
          <span className={`badge ${result.result_type}`}>
            {kindLabel(result.result_type)}
          </span>
          {index === 0 && <span>Most relevant result</span>}
          {result.result_type === "decision" && (
            <span>{dateLabel(timeline?.date, timeline?.date_status)}</span>
          )}
        </div>
        <h2 dir="auto">{title}</h2>
        {result.item?.title && <p dir="auto">{result.item.description}</p>}
        {result.result_type === "document" && (
          <p className="document-preview" dir="auto">
            {result.text}
          </p>
        )}
        {result.result_type === "decision" && (
          <div className="rationale">
            <span className="eyebrow">Why this decision</span>
            <p dir="auto">
              {result.item?.rationale ||
                "No rationale established in the source."}
            </p>
          </div>
        )}
        <div className="record-footer">
          <button
            className="evidence-button"
            onClick={() =>
              select({ title, evidence: result.evidence_references })
            }
          >
            Inspect evidence <span>↗</span>
          </button>
          {result.result_type === "action_item" && result.item_id && (
            <button
              className="text-button"
              onClick={() => openAction(result.item_id!)}
            >
              View latest state & history
            </button>
          )}
        </div>
        <details className="advanced">
          <summary>Retrieval details</summary>
          <p>
            Baseline rank {row.base_rank} · Final rank {row.reranked_rank} ·
            Similarity {result.cosine_score.toFixed(3)} · Reranking{" "}
            {search.rerank_status}
          </p>
          {result.result_type === "action_item" && (
            <p>
              This is the original commitment. Open its history for the latest
              known state.
            </p>
          )}
        </details>
      </article>
    );
  });
  return (
    <div className="results">
      <div className="section-heading">
        <h2>Retrieved evidence</h2>
        <span>{search.results.length} results</span>
      </div>
      {!search.results.length && (
        <div className="empty-inline">
          <h3>No matching results</h3>
          <p>Try a person, supplier, or specific project event.</p>
        </div>
      )}
      {records[0]}
      {records.length > 1 && (
        <details className="more-results">
          <summary>Explore {records.length - 1} more results</summary>
          <div>{records.slice(1)}</div>
        </details>
      )}
    </div>
  );
}
export function ActionHistory({
  item,
  select,
}: {
  item: Action;
  select: (s: Selection) => void;
}) {
  return (
    <section className="action-history">
      <div className="section-heading">
        <h2>Commitment history</h2>
        <span className={`badge ${item.state}`}>{stateLabel(item.state)}</span>
      </div>
      <h3 dir="auto">{item.action.description}</h3>
      <p className="muted small">
        One original commitment, with a preserved trail of later evidence.
      </p>
      <dl className="action-facts">
        <div>
          <dt>Current owner</dt>
          <dd dir="auto">{item.owner || "Unknown owner"}</dd>
        </div>
        <div>
          <dt>Deadline in source</dt>
          <dd dir="auto">{item.action.deadline_text || "Not specified"}</dd>
        </div>
      </dl>
      <ol className="history">
        {item.history.map((event) => (
          <li key={event.event_id}>
            <div className="record-meta">
              <span className="eyebrow">
                {event.event_type === "assignment"
                  ? "Original assignment"
                  : stateLabel(event.event_type)}
              </span>
              <time>{dateLabel(event.date)}</time>
            </div>
            <p dir="auto">{event.description}</p>
            {!event.applied && (
              <p className="notice">
                Retained as evidence; not applied to current state.
              </p>
            )}
            <button
              className="text-button"
              onClick={() =>
                select({
                  title: `${stateLabel(event.event_type)} evidence`,
                  evidence: event.evidence_references,
                })
              }
            >
              Inspect {event.event_type} evidence ↗
            </button>
          </li>
        ))}
      </ol>
      {item.warnings.map((w, i) => (
        <p className="notice" key={i}>
          {w}
        </p>
      ))}
      <details className="advanced">
        <summary>Commitment identity</summary>
        <p className="technical">{item.action.id}</p>
        <p>The assignment and later events refer to this same action ID.</p>
      </details>
    </section>
  );
}
