import { MixedText } from "./mixed-text";
import type { Action, Project, Selection } from "@/lib/types";
import { dateLabel, filterActions, stateLabel } from "@/lib/format";
import { ActionHistory } from "./results";
export function OpenLoopsView({
  project,
  busy,
  actions,
  action,
  loopTab,
  setLoopTab,
  setAction,
  setSelection,
  openAction,
  counts,
}: {
  project: Project | null;
  busy: string;
  actions: Action[];
  action: Action | null;
  loopTab: string;
  setLoopTab: (value: string) => void;
  setAction: (value: Action | null) => void;
  setSelection: (value: Selection | null) => void;
  openAction: (id: string) => Promise<void>;
  counts: { unresolved: number; completed: number; cancelled: number };
}) {
  return (
    <>
      <div
        className="loop-tabs"
        role="tablist"
        aria-label="Commitment state"
        onKeyDown={(e) => {
          const tabs = ["unresolved", "completed", "cancelled"];
          const index = tabs.indexOf(loopTab);
          const next =
            e.key === "ArrowRight"
              ? tabs[(index + 1) % 3]
              : e.key === "ArrowLeft"
                ? tabs[(index + 2) % 3]
                : e.key === "Home"
                  ? tabs[0]
                  : e.key === "End"
                    ? tabs[2]
                    : null;
          if (next) {
            e.preventDefault();
            setLoopTab(next);
            setAction(null);
            setSelection(null);
            document.getElementById(`tab-${next}`)?.focus();
          }
        }}
      >
        {(["unresolved", "completed", "cancelled"] as const).map((tab) => (
          <button
            role="tab"
            tabIndex={loopTab === tab ? 0 : -1}
            id={`tab-${tab}`}
            aria-controls="commitments"
            aria-selected={loopTab === tab}
            key={tab}
            onClick={() => {
              setLoopTab(tab);
              setAction(null);
              setSelection(null);
            }}
          >
            {tab === "unresolved" ? "Open loops" : stateLabel(tab)}
            <span>{counts[tab]}</span>
          </button>
        ))}
      </div>
      <div id="commitments" role="tabpanel" aria-labelledby={`tab-${loopTab}`}>
        {!project?.snapshot_id ? (
          <div className="empty-inline">
            <h2>Commitments will appear here</h2>
            <p>
              Process project documents to find assignments and their supporting
              evidence.
            </p>
          </div>
        ) : !filterActions(actions, loopTab).length ? (
          <div className="empty-inline">
            <div className="empty-check" aria-hidden="true">
              {loopTab === "unresolved" ? "✓" : "◌"}
            </div>
            <h2>
              {loopTab === "unresolved"
                ? "No unresolved commitments found"
                : `No ${loopTab} commitments found`}
            </h2>
            <p>
              {loopTab === "unresolved"
                ? "Based on the evidence processed so far. View completed commitments to trace their history."
                : "Later evidence may establish a change in an original commitment."}
            </p>
            {counts.completed > 0 && loopTab === "unresolved" && (
              <button
                className="text-button"
                onClick={() => setLoopTab("completed")}
              >
                View completed commitments →
              </button>
            )}
          </div>
        ) : (
          filterActions(actions, loopTab).map((item) => (
            <button
              className={`action-row ${action?.action.id === item.action.id ? "selected" : ""}`}
              key={item.action.id}
              disabled={busy === "history"}
              onClick={() => void openAction(item.action.id)}
            >
              <div className="record-meta">
                <span className={`badge ${item.state}`}>
                  {stateLabel(item.state)}
                </span>
                <span dir="auto">{item.owner || "Unknown owner"}</span>
                <span>{dateLabel(item.latest_known_date)}</span>
              </div>
              <h3 dir="auto">
                <MixedText text={item.action.description} />
              </h3>
              <p dir="auto">
                Deadline: {item.action.deadline_text || "Not specified"}
              </p>
              <span className="text-link">View commitment history ↗</span>
            </button>
          ))
        )}
      </div>
      {busy === "history" && (
        <div role="status" className="loading-state">
          <span className="spinner" /> Loading commitment history…
        </div>
      )}
      {action && <ActionHistory item={action} select={setSelection} />}
    </>
  );
}
