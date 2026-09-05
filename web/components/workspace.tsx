"use client";
import { useEffect, useRef, useState } from "react";
import { api, post } from "@/lib/api";
import { DocumentsView } from "./documents-view";
import { OpenLoopsView } from "./open-loops-view";
import type { Action, Memory, Project, Search, Selection } from "@/lib/types";
import { EvidencePanel } from "./evidence-panel";
import { Timeline } from "./timeline";
import { DecisionRecord, SearchResults } from "./results";

const prompts = [
  "ليش غيرنا المورد؟",
  "Why did the team replace Falcon Systems?",
  "وش صار على Falcon API integration والvendor الجديد؟",
];
type View = "decisions" | "documents" | "loops";
export function Workspace() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<View>("decisions");
  const [memory, setMemory] = useState<Memory>({ timeline: [], risks: [] });
  const [actions, setActions] = useState<Action[]>([]);
  const [action, setAction] = useState<Action | null>(null);
  const [loopTab, setLoopTab] = useState("unresolved");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<Search | null>(null);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(false);
  const [configured, setConfigured] = useState(true);
  const [loading, setLoading] = useState(true);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [revision, setRevision] = useState(0);
  const [newName, setNewName] = useState("");
  const [showNew, setShowNew] = useState(false);
  const activeId = useRef<string | null>(null);
  const processing = project?.status === "processing";

  function adopt(p: Project) {
    activeId.current = p.id;
    setRevision((v) => v + 1);
    setMemoryLoading(!!p.snapshot_id);
    setProject(p);
    setSelection(null);
    setSearch(null);
    setAction(null);
    setMemory({ timeline: [], risks: [] });
    setActions([]);
    setLoopTab("unresolved");
    localStorage.setItem("athar-project", p.id);
    setProjects((prev) => [p, ...prev.filter((item) => item.id !== p.id)]);
  }
  async function connect() {
    setLoading(true);
    setError("");
    try {
      const [health, list] = await Promise.all([
        api<{ ai_configured: boolean }>("/api/health"),
        api<Project[]>("/api/projects"),
      ]);
      setConnected(true);
      setConfigured(health.ai_configured);
      setProjects(list);
      const saved = localStorage.getItem("athar-project");
      const selected = list.find((p) => p.id === saved) || list[0];
      if (selected) adopt(selected);
    } catch (e) {
      setError((e as Error).message);
      setConnected(false);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void connect();
  }, []); // One initial local connection.
  useEffect(() => {
    if (!project || !processing) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const id = project.id;
    const poll = async () => {
      try {
        const next = await api<Project>(`/api/projects/${id}`);
        if (stopped || activeId.current !== id) return;
        setProject(next);
        setProjects((prev) => prev.map((p) => (p.id === id ? next : p)));
        if (next.status === "ready") {
          setView("decisions");
          setError("");
        }
        if (next.status === "processing") timer = setTimeout(poll, 1500);
      } catch (e) {
        if (!stopped) {
          setError((e as Error).message);
          timer = setTimeout(poll, 4000);
        }
      }
    };
    timer = setTimeout(poll, 800);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [project?.id, processing]);
  useEffect(() => {
    if (!project?.snapshot_id) return;
    setMemoryLoading(true);
    let stopped = false;
    const id = project.id;
    Promise.all([
      api<Memory>(`/api/decisions?project_id=${id}`),
      api<Action[]>(`/api/actions?project_id=${id}`),
    ])
      .then(([m, a]) => {
        if (!stopped) {
          setMemory(m);
          setActions(a);
        }
      })
      .catch((e) => {
        if (!stopped) setError(e.message);
      }).finally(() => { if (!stopped) setMemoryLoading(false); });
    return () => {
      stopped = true;
    };
  }, [project?.id, project?.snapshot_id, revision]);

  async function loadAtlas() {
    setBusy("atlas");
    setError("");
    try {
      adopt(await post<Project>("/api/projects/atlas/load"));
      setView("documents");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function createProject(event: React.FormEvent) {
    event.preventDefault();
    setBusy("create");
    setError("");
    try {
      adopt(
        await post<Project>("/api/projects", {
          name: newName.trim() || "Untitled project",
        }),
      );
      setNewName("");
      setShowNew(false);
      setView("documents");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function upload(files: FileList | null) {
    if (!project || !files?.length) return;
    const id = project.id;
    setBusy("upload");
    setError("");
    try {
      for (const file of Array.from(files)) {
        if (file.size > 10 * 1024 * 1024)
          throw new Error("Each file must be no larger than 10 MB.");
        const form = new FormData();
        form.append("project_id", id);
        form.append("file", file);
        const next = await api<Project>("/api/documents/upload", {
          method: "POST",
          body: form,
        });
        if (activeId.current === id) setProject(next);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function processProject() {
    if (!project) return;
    const id = project.id;
    setBusy("process");
    setError("");
    try {
      const next = await post<Project>("/api/process", { project_id: id });
      if (activeId.current === id) setProject(next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function ask(question = query) {
    if (!project?.snapshot_id || !question.trim()) return;
    const id = project.id;
    setBusy("search");
    setError("");
    setSearch(null);
    setSelection(null);
    setView("decisions");
    setSearchedQuery(question);
    setQuery(question);
    try {
      const result = await post<Search>("/api/search", {
        project_id: id,
        query: question,
      });
      if (activeId.current === id) {
        setSearch(result);
        const top = result.results[0]?.result;
        if (top)
          setSelection({
            title:
              top.item?.title || top.item?.description || "Document evidence",
            evidence: top.evidence_references,
          });
      }
    } catch (e) {
      if (activeId.current === id) setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  async function openAction(id: string) {
    if (!project) return;
    const projectId = project.id;
    setError("");
    setBusy("history");
    try {
      const item = await api<Action>(
        `/api/actions/${id}?project_id=${projectId}`,
      );
      if (activeId.current !== projectId) return;
      setAction(item);
      setView("loops");
      setLoopTab(
        item.unresolved
          ? "unresolved"
          : item.state === "completed"
            ? "completed"
            : "cancelled",
      );
      setSelection({
        title: item.action.description,
        evidence:
          item.history.at(-1)?.evidence_references ||
          item.action.evidence_references,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  function navigate(next: View) {
    setView(next);
    setSelection(null);
  }
  const counts = {
    unresolved: actions.filter((a) => a.unresolved).length,
    completed: actions.filter((a) => a.state === "completed").length,
    cancelled: actions.filter((a) => a.state === "cancelled").length,
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar" aria-label="Workspace navigation">
        <a className="brand" href="/" aria-label="Athar AI home">
          <span className="brand-mark" lang="ar">
            أثر
          </span>
          <span>
            Athar<span className="brand-ai"> AI</span>
            <small>DECISION INTELLIGENCE</small>
          </span>
        </a>
        <div className="workspace-label eyebrow">Local workspace</div>
        <label className="sr-only" htmlFor="project-select">
          Current project
        </label>
        <select
          id="project-select"
          className="project-select"
          value={project?.id || ""}
          disabled={!!busy}
          onChange={(e) => {
            const p = projects.find((p) => p.id === e.target.value);
            if (p) {
              adopt(p);
              setError("");
            }
          }}
        >
          <option value="" disabled>
            Select a project
          </option>
          {projects.map((p) => (
            <option value={p.id} key={p.id}>
              {p.name}
              {p.synthetic ? " · Demo" : ""}
            </option>
          ))}
        </select>
        <button
          className="new-project"
          onClick={() => setShowNew(!showNew)}
          disabled={!connected || !!busy}
        >
          ＋ New project
        </button>
        {showNew && (
          <form className="new-project-form" onSubmit={createProject}>
            <label htmlFor="project-name">Project name</label>
            <input
              id="project-name"
              autoFocus
              maxLength={80}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Delivery programme"
            />
            <button className="primary-button" disabled={!!busy}>
              Create project
            </button>
          </form>
        )}
        <nav aria-label="Project views">
          {(
            [
              { id: "documents", label: "Documents", icon: "▤" },
              { id: "decisions", label: "Decisions", icon: "◇" },
              { id: "loops", label: "Open Loops", icon: "◌" },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              className={view === item.id ? "nav-item active" : "nav-item"}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
              {item.id === "loops" && counts.unresolved > 0 && (
                <span className="nav-count">{counts.unresolved}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="demo-note">
          <span className="eyebrow">Explore the example</span>
          <h3>Project Atlas</h3>
          <p>
            A supplier decision.
            <br />A change of direction.
            <br />A commitment followed through.
          </p>
          <span className="synthetic-label">
            Synthetic Arabic-English documents
          </span>
          <button
            className="atlas-button"
            onClick={loadAtlas}
            disabled={!connected || !!busy || processing}
          >
            {busy === "atlas" ? "Loading…" : "Load Project Atlas"}
            <span>↗</span>
          </button>
          <small>
            Runs the real Athar pipeline using your Python server’s API access.
          </small>
        </div>
        <div className="sidebar-foot">
          <span className={`status-dot ${connected ? "online" : ""}`} />
          {connected ? "Local API connected" : "API disconnected"}
          <span className="version">PHASE 05</span>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <div>
            <span className="muted">Workspace</span>
            <span className="slash">/</span>
            <strong dir="auto">{project?.name || "Getting started"}</strong>
            {project?.synthetic && (
              <span className="demo-badge">Synthetic demo</span>
            )}
          </div>
          <span className="topbar-label">
            AR <span>＋</span> EN
          </span>
        </header>
        <div className="content-grid">
          <main id="main" className="main-content">
            {error && (
              <div className="error-banner" role="alert">
                <strong>Something needs attention</strong>
                <p>{error}</p>
                <button className="text-button" onClick={() => void connect()}>
                  Reconnect & refresh
                </button>
                <button
                  className="icon-button"
                  aria-label="Dismiss error"
                  onClick={() => setError("")}
                >
                  ×
                </button>
              </div>
            )}
            {!configured && connected && (
              <div className="notice">
                Add an OpenAI API key to the project’s Python .env before
                processing or searching. Keep credentials out of the frontend.
              </div>
            )}
            {processing && (
              <div className="processing-banner" role="status">
                <span className="spinner" />
                <div>
                  <strong>Building project memory</strong>
                  <p>{project.stage}</p>
                  <small>
                    You can navigate while processing continues. This may take a
                    few minutes.
                  </small>
                </div>
              </div>
            )}
            {project?.error && (
              <div className="error-banner" role="alert">
                <strong>Processing did not finish</strong>
                <p>{project.error}</p>
                <button
                  className="text-button"
                  disabled={!!busy}
                  onClick={processProject}
                >
                  Retry processing
                </button>
              </div>
            )}
            <div className="page-heading">
              <span className="eyebrow">
                {view === "documents"
                  ? "Project knowledge"
                  : view === "loops"
                    ? "Commitment intelligence"
                    : "Organizational memory"}
              </span>
              <h1>
                {view === "documents"
                  ? "Every decision starts with evidence."
                  : view === "loops"
                    ? "What still needs follow-through?"
                    : "Understand the decision.\nTrace what changed."}
              </h1>
              <p>
                {view === "documents"
                  ? "Bring your project documents together. Keep their evidence intact."
                  : view === "loops"
                    ? "Original commitments, latest known states, and the evidence connecting them."
                    : "Decisions, rationale, and commitments — grounded in your team’s words."}
              </p>
            </div>
            {loading || memoryLoading ? (
              <div className="loading-state" role="status">
                <span className="spinner" /> {memoryLoading ? "Loading project memory…" : "Connecting to your local workspace…"}
              </div>
            ) : (
              <>
                {view === "decisions" && (
                  <>
                    <form
                      className="question-box"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void ask();
                      }}
                    >
                      <label htmlFor="question" className="eyebrow">
                        Ask your project{" "}
                        <span lang="ar" dir="rtl">
                          اسأل مشروعك
                        </span>
                      </label>
                      <div className="question-row">
                        <textarea
                          id="question"
                          rows={2}
                          maxLength={2000}
                          dir="auto"
                          placeholder="What did we decide, and why?"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              if (!busy) void ask();
                            }
                          }}
                        />
                        <button
                          className="ask-button"
                          disabled={
                            !project?.snapshot_id || !!busy || !query.trim()
                          }
                          aria-label="Search project"
                        >
                          {busy === "search" ? (
                            <span className="spinner" />
                          ) : (
                            "↗"
                          )}
                        </button>
                      </div>
                      <div className="question-foot">
                        <span>Arabic, English, or both.</span>
                        <span>Evidence comes first.</span>
                      </div>
                    </form>
                    <div className="prompt-list" aria-label="Example questions">
                      {prompts.map((prompt) => (
                        <button
                          key={prompt}
                          dir="auto"
                          disabled={!project?.snapshot_id || !!busy}
                          onClick={() => void ask(prompt)}
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
                    {busy === "search" && (
                      <div className="loading-state" role="status">
                        <span className="spinner" /> Retrieving and checking
                        relevant project evidence…
                      </div>
                    )}
                    {search ? (
                      <>
                        <div className="search-context">
                          <span>
                            Results for{" "}
                            <strong dir="auto">{searchedQuery}</strong>
                          </span>
                          <button
                            className="text-button"
                            onClick={() => {
                              setSearch(null);
                              setSelection(null);
                            }}
                          >
                            Clear search
                          </button>
                        </div>
                        <SearchResults
                          search={search}
                          select={setSelection}
                          openAction={openAction}
                        />
                        <Timeline
                          entries={search.timeline}
                          select={setSelection}
                        />
                      </>
                    ) : (
                      busy !== "search" && (
                        <>
                          {project?.snapshot_id ? (
                            <>
                              {!!memory.rejected_records && (
                                <div className="notice">
                                  {memory.rejected_records} proposed record(s)
                                  were omitted because source verification
                                  failed. Only accepted records are shown;
                                  search can still retrieve the original
                                  documents.
                                </div>
                              )}
                              <div className="section-heading">
                                <h2>Project decisions</h2>
                                <span>
                                  {memory.timeline.length} verified records
                                </span>
                              </div>
                              {memory.timeline.length ? (
                                memory.timeline.map((d) => (
                                  <DecisionRecord
                                    key={d.decision_id}
                                    decision={d}
                                    select={setSelection}
                                  />
                                ))
                              ) : (
                                <div className="empty-inline">
                                  <h3>No verified decisions extracted</h3>
                                  <p>
                                    You can still search the source documents,
                                    or upload more evidence.
                                  </p>
                                </div>
                              )}
                              <Timeline
                                entries={memory.timeline}
                                select={setSelection}
                              />
                              {memory.risks.length > 0 && (
                                <section className="risks-section">
                                  <div className="section-heading">
                                    <h2>Recorded risks</h2>
                                    <span>{memory.risks.length} records</span>
                                  </div>
                                  {memory.risks.map((risk) => (
                                    <article className="risk-row" key={risk.id}>
                                      <span className="badge risk">Risk</span>
                                      <p dir="auto">{risk.description}</p>
                                      <button
                                        className="text-button"
                                        onClick={() =>
                                          setSelection({
                                            title: risk.description,
                                            evidence: risk.evidence_references,
                                          })
                                        }
                                      >
                                        Inspect evidence ↗
                                      </button>
                                    </article>
                                  ))}
                                </section>
                              )}
                            </>
                          ) : (
                            <div className="welcome-state">
                              <div className="eyebrow">
                                A clearer organizational memory
                              </div>
                              <h2>
                                Your project has a story.
                                <br />
                                Make it traceable.
                              </h2>
                              <p>
                                Load the synthetic Project Atlas demo, or create
                                a workspace and process your own documents.
                              </p>
                              <div className="welcome-steps">
                                <span>
                                  <b>01</b> What was decided
                                </span>
                                <span>
                                  <b>02</b> Why it changed
                                </span>
                                <span>
                                  <b>03</b> What remains open
                                </span>
                              </div>
                              <button
                                className="primary-button"
                                disabled={!connected || !!busy || processing}
                                onClick={loadAtlas}
                              >
                                Load Project Atlas <span>↗</span>
                              </button>
                            </div>
                          )}
                        </>
                      )
                    )}
                  </>
                )}
                {view === "documents" && (
                  <DocumentsView
                    project={project}
                    busy={busy}
                    processing={!!processing}
                    upload={upload}
                    processProject={processProject}
                  />
                )}
                {view === "loops" && (
                  <OpenLoopsView
                    project={project}
                    busy={busy}
                    actions={actions}
                    action={action}
                    loopTab={loopTab}
                    setLoopTab={setLoopTab}
                    setAction={setAction}
                    setSelection={setSelection}
                    openAction={openAction}
                    counts={counts}
                  />
                )}
              </>
            )}
            <footer className="main-foot">
              <span>
                Athar AI — <span lang="ar">أثر</span>
              </span>
              <span>Organizational decision intelligence</span>
            </footer>
          </main>
          <EvidencePanel
            selection={selection}
            close={() => setSelection(null)}
          />
        </div>
      </div>
    </div>
  );
}
