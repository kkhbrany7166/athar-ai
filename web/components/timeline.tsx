import type { Decision, Selection } from "@/lib/types";
import { dateLabel } from "@/lib/format";
export function Timeline({
  entries,
  select,
}: {
  entries: Decision[];
  select: (value: Selection) => void;
}) {
  if (!entries.length) return null;
  return (
    <section className="timeline-section" aria-label="Decision timeline">
      <div className="section-heading">
        <h2>Decision timeline</h2>
        <span>Evidence-backed chronology</span>
      </div>
      <p className="muted small">
        A record of change. Chronology does not establish which decision is
        authoritative.
      </p>
      <ol className="timeline">
        {entries.map((entry) => (
          <li key={entry.decision_id}>
            <time dateTime={entry.date || undefined}>
              {dateLabel(entry.date, entry.date_status)}
            </time>
            <button
              className="timeline-entry"
              onClick={() =>
                select({
                  title: entry.title,
                  evidence: entry.evidence_references,
                })
              }
            >
              <span dir="auto">{entry.title}</span>
              <span className="text-link">Inspect evidence ↗</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
