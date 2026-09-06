import type { Project } from "@/lib/types";
import { sizeLabel, stateLabel } from "@/lib/format";
export function DocumentsView({
  project,
  busy,
  processing,
  upload,
  processProject,
}: {
  project: Project | null;
  busy: string;
  processing: boolean;
  upload: (files: FileList | null) => Promise<void>;
  processProject: () => Promise<void>;
}) {
  return (
    <>
      {!project ? (
        <div className="empty-inline">
          <h2>Start a project workspace</h2>
          <p>
            Create a project from the sidebar, or load the synthetic Atlas
            example.
          </p>
        </div>
      ) : (
        <>
          <div className="upload-area">
            <span className="upload-symbol" aria-hidden="true">
              ↑
            </span>
            <h2>Add source documents</h2>
            <p>
              Text, Markdown, or text-based PDF · Up to 10 MB each · 30 files
              per project
            </p>
            <label
              className={`upload-button ${processing || busy ? "disabled" : ""}`}
            >
              Choose files
              <input
                aria-label="Upload documents"
                type="file"
                accept=".txt,.md,.pdf"
                multiple
                disabled={processing || !!busy}
                onChange={(e) => {
                  void upload(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
            <small>
              Stored in your local workspace. Processing sends document text to
              OpenAI.
            </small>
          </div>
          <div className="section-heading">
            <h2>
              Project documents{" "}
              <span className="muted">{project.documents.length}</span>
            </h2>
            <button
              className="primary-button"
              disabled={
                !!busy ||
                processing ||
                !project.documents.some((d) => d.status !== "ready")
              }
              onClick={processProject}
            >
              {busy === "upload"
                ? "Uploading…"
                : processing
                  ? "Processing…"
                  : "Process documents"}
            </button>
          </div>
          <div className="document-list">
            {project.documents.map((doc) => (
              <article className="document-row" key={doc.id}>
                <span className="file-icon" aria-hidden="true">
                  ▤
                </span>
                <div>
                  <strong dir="auto">{doc.filename}</strong>
                  <p>
                    {sizeLabel(doc.size)}
                    {doc.kind === "followup"
                      ? " · Later lifecycle evidence"
                      : " · Project source"}
                  </p>
                </div>
                <span className={`badge ${doc.status}`}>
                  {stateLabel(doc.status)}
                </span>
              </article>
            ))}
            {!project.documents.length && (
              <p className="empty-inline">
                No documents yet. Choose your first source above.
              </p>
            )}
          </div>
          <p className="muted small">
            New files add to existing memory. Later evidence can update original
            commitments; previous snapshots are retained. Scanned PDFs require
            OCR before upload.
          </p>
        </>
      )}
    </>
  );
}
