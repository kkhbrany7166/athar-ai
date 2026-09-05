import { useEffect, useRef } from "react";
import type { Selection } from "@/lib/types";
export function EvidencePanel({
  selection,
  close,
}: {
  selection: Selection | null;
  close: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (selection && window.matchMedia("(max-width: 1000px)").matches) {
      panel.current?.scrollIntoView({ block: "start" });
      panel.current?.focus({ preventScroll: true });
    }
  }, [selection]);
  return (
    <aside
      ref={panel}
      tabIndex={-1}
      className={`evidence-panel ${selection ? "has-evidence" : ""}`}
      aria-label="Source evidence"
    >
      <div className="panel-heading">
        <span className="eyebrow">Source evidence</span>
        {selection && (
          <button
            className="icon-button"
            aria-label="Close evidence"
            onClick={close}
          >
            ×
          </button>
        )}
      </div>
      {selection ? (
        <>
          <div className="evidence-intro">
            <span className="verified">✓ Verified excerpt</span>
            <h3 dir="auto">{selection.title}</h3>
            <p>
              Exact text from the source. Preserved in its original language.
            </p>
          </div>
          {selection.evidence.map((ref, index) => (
            <article className="citation" key={`${ref.chunk_id}-${index}`}>
              <div className="source-line">
                <span aria-hidden="true">▤</span>
                <strong dir="auto">{ref.source}</strong>
              </div>
              <div className="source-meta">
                {ref.page === null ? "Text document" : `Page ${ref.page}`} ·
                Evidence {index + 1}
              </div>
              <blockquote dir="auto">{ref.excerpt}</blockquote>
              <details>
                <summary>Source details</summary>
                <dl className="technical">
                  <dt>Document ID</dt>
                  <dd>{ref.document_id}</dd>
                  <dt>Chunk ID</dt>
                  <dd>{ref.chunk_id}</dd>
                </dl>
              </details>
            </article>
          ))}
        </>
      ) : (
        <div className="evidence-empty">
          <span className="evidence-symbol" aria-hidden="true">
            “
          </span>
          <h3>The source behind the story.</h3>
          <p>
            Select a decision, commitment, or search result to inspect its exact
            supporting evidence.
          </p>
          <div className="source-promise">
            Source filename
            <br />
            Page reference
            <br />
            Verified excerpt
          </div>
        </div>
      )}
      <p className="panel-foot">
        Grounded in your documents.
        <br />
        Interpretations still deserve human review.
      </p>
    </aside>
  );
}
