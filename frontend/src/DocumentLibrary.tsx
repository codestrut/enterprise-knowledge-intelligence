import { useEffect, useMemo, useRef, useState } from "react";
import { ApiRequestError, deleteDocument, MAX_UPLOAD_BYTES, uploadDocument } from "./api/client";
import type { DocumentRecord, UploadResponse } from "./api/types";
import { AppLink } from "./AppShell";
import { Icon } from "./Icons";
import { useKnowledgeBase } from "./KnowledgeBaseContext";
import { useAuth } from "./AuthContext";

type UploadState = "idle" | "validating" | "uploading" | "success" | "error" | "stopped";

export default function DocumentLibrary() {
  const { documents, status, documentsError, refreshing, lastUpdated, refresh } = useKnowledgeBase();
  const { permissions, profile } = useAuth();
  // Fail closed: unknown permissions grant nothing. Readers cannot upload or delete.
  const isReader = profile?.role === "reader";
  const canUpload = !isReader && (permissions?.has("documents:upload") ?? false);
  const canDelete = !isReader && (permissions?.has("documents:delete") ?? false);
  const [file, setFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadElapsed, setUploadElapsed] = useState(0);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [filter, setFilter] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<DocumentRecord | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [deleteMessage, setDeleteMessage] = useState("");
  const [dialogMessage, setDialogMessage] = useState("");
  const [dialogBusy, setDialogBusy] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadController = useRef<AbortController | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const deleteTriggerRef = useRef<HTMLElement | null>(null);
  const uploadSuccessRef = useRef<HTMLDivElement>(null);
  const deleteStatusRef = useRef<HTMLParagraphElement>(null);
  const rowRefs = useRef<Record<string, HTMLElement | null>>({});
  const busy = uploadState === "validating" || uploadState === "uploading" || uncertain;

  useEffect(() => {
    if (uploadState !== "uploading") return;
    const timer = window.setInterval(() => setUploadElapsed((elapsed) => elapsed + 1), 1000);
    return () => window.clearInterval(timer);
  }, [uploadState]);

  useEffect(() => {
    const active = uploadState === "uploading" || uncertain;
    if (!active) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "An upload may still be processing."; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [uploadState, uncertain]);

  useEffect(() => {
    const guard = (event: Event) => {
      if ((uploadState === "uploading" || uncertain) && !window.confirm("The server may still be uploading and indexing this PDF. Leave this page?")) event.preventDefault();
    };
    window.addEventListener("ekip:before-navigate", guard);
    return () => window.removeEventListener("ekip:before-navigate", guard);
  }, [uploadState, uncertain]);

  async function runRefresh() {
    const snapshot = await refresh();
    if (uploadState === "stopped" && (snapshot.documentsError || (file && !snapshot.documents.some((document) => safeFilename(document.filename).toLowerCase() === safeFilename(file.name).toLowerCase())))) {
      setUploadMessage(snapshot.documentsError ? "The document list could not be refreshed, so upload status is still unknown. Try refreshing again later." : "The file has not appeared in the document list yet. Server processing may still be running; refresh again later.");
      setUncertain(true);
      return;
    }
    setUncertain(false);
    if (uploadState === "stopped") setUploadState("idle");
  }

  function selectFile(next: File | null) {
    setFile(next);
    setUploadResult(null);
    setUploadMessage("");
    if (uploadState === "error" || uploadState === "success") setUploadState("idle");
  }

  async function submitUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || busy) return;
    setUploadState("validating");
    setUploadMessage("");
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadState("error"); setUploadMessage("Choose a PDF file. The API accepts PDF documents only."); return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadState("error"); setUploadMessage("This file exceeds the backend’s 25 MB upload limit. Choose a smaller PDF."); return;
    }
    let header = "";
    try { header = new TextDecoder().decode(await file.slice(0, 5).arrayBuffer()); }
    catch { header = ""; }
    if (header !== "%PDF-") {
      setUploadState("error"); setUploadMessage("The selected file does not have a valid PDF signature. Choose a valid PDF."); return;
    }

    const controller = new AbortController();
    uploadController.current = controller;
    setUploadElapsed(0);
    setUploadState("uploading");
    setUncertain(false);
    try {
      const response = await uploadDocument(file, controller.signal);
      setUploadResult(response);
      setUploadState("success");
      setUploadMessage(`${safeFilename(response.document.filename || file.name)} was indexed successfully.`);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await refresh();
      setAnnouncement(`${safeFilename(response.document.filename || file.name)} uploaded and indexed.`);
      window.requestAnimationFrame(() => uploadSuccessRef.current?.focus());
    } catch (error) {
      if (controller.signal.aborted) {
        setUploadState("stopped");
        setUncertain(true);
        setUploadMessage("You stopped waiting. The server may still finish indexing this PDF. Refresh the library to check its status.");
      } else if (error instanceof ApiRequestError && [408, 502, 503, 504].includes(error.status ?? 0)) {
        setUploadState("stopped");
        setUncertain(true);
        setUploadMessage(`${error.message} Refresh the library before trying another upload.`);
      } else if (error instanceof TypeError) {
        setUploadState("stopped");
        setUncertain(true);
        setUploadMessage(`${error.message} The server may still have received the PDF. Refresh the library before retrying.`);
      } else {
        setUploadState("error");
        setUploadMessage(uploadErrorMessage(error));
        const existing = duplicateRecord(error);
        if (existing?.document_id) {
          const node = rowRefs.current[existing.document_id];
          if (node) { node.scrollIntoView?.({ block: "center" }); node.focus({ preventScroll: true }); }
        }
      }
    } finally { uploadController.current = null; }
  }

  function stopWaiting() { uploadController.current?.abort(); }

  function requestDelete(document: DocumentRecord, trigger?: HTMLElement | null) {
    deleteTriggerRef.current = trigger ?? (document.activeElement as HTMLElement | null);
    setDeleteTarget(document);
    setDialogMessage("");
    setDialogBusy(false);
    window.requestAnimationFrame(() => {
      if (dialogRef.current && !dialogRef.current.open) {
        dialogRef.current.showModal();
        cancelButtonRef.current?.focus();
      }
    });
  }

  function handleDialogClose() {
    if (!dialogBusy) {
      setDeleteTarget(null);
      setDialogMessage("");
      deleteTriggerRef.current?.focus();
    }
  }

  async function confirmDelete() {
    if (!deleteTarget?.document_id || deleting || busy) return;
    const id = deleteTarget.document_id;
    setDeleting(id); setDialogBusy(true); setDialogMessage(""); setDeleteMessage("");
    try {
      const result = await deleteDocument(id);
      deleteTriggerRef.current = null;
      dialogRef.current?.close();
      setDeleteTarget(null);
      const name = safeFilename(result.filename || deleteTarget.filename || "Document");
      setDeleteMessage(result.cleanup_required ? `${name} was removed from search, but its stored file still needs cleanup.` : result.file_deleted ? `${name} was removed from search and its stored file was deleted.` : `${name} was removed from search; the API did not confirm that its stored file was deleted.`);
      await refresh();
      setAnnouncement(`${name} was deleted from the knowledge base.`);
      window.requestAnimationFrame(() => deleteStatusRef.current?.focus());
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 404) {
        deleteTriggerRef.current = null;
        dialogRef.current?.close(); setDeleteTarget(null);
        setDeleteMessage("This document no longer exists. The library has been refreshed.");
        await refresh();
        window.requestAnimationFrame(() => deleteStatusRef.current?.focus());
      } else {
        setDialogMessage(uploadErrorMessage(error));
      }
    } finally { setDeleting(null); setDialogBusy(false); }
  }

  const visibleDocuments = useMemo(() => {
    if (!filter.trim()) return documents;
    return documents.filter((document) => safeFilename(document.filename).toLowerCase().includes(filter.trim().toLowerCase()));
  }, [documents, filter]);
  const showPageCount = documents.some((doc) => typeof doc.page_count === "number");
  const showChunkCount = documents.some((doc) => typeof doc.chunk_count === "number");

  return <main className="page-section library-page">
    <section className="compact-heading"><div><p className="eyebrow">KNOWLEDGE BASE</p><h1 tabIndex={-1}>Document management</h1><p>Upload PDFs, review indexed documents and safely remove documents from search.</p></div><button className="secondary-button" type="button" onClick={() => void runRefresh()} disabled={refreshing || busy}><Icon name="refresh"/>{refreshing ? "Refreshing" : "Refresh library"}</button></section>

    {canUpload && <section className="upload-card" aria-labelledby="upload-heading"><div className="card-heading"><span className="large-icon"><Icon name="upload"/></span><div><h2 id="upload-heading">Upload a PDF</h2><p>PDF files up to 25 MB are accepted. Indexing runs synchronously; keep this tab open while it is processing.</p></div></div>
      <form onSubmit={(event) => void submitUpload(event)}>
        <label className="file-label" htmlFor="pdf-file">Choose PDF file <span>Required · maximum 25 MB</span></label>
        <input ref={fileInput} id="pdf-file" type="file" accept="application/pdf,.pdf" disabled={busy} onChange={(event) => selectFile(event.target.files?.[0] ?? null)}/>
        {file && <div className="selected-file"><Icon name="document"/><span className="file-name">{safeFilename(file.name)}</span><span>{formatBytes(file.size)}</span><button className="icon-button" type="button" onClick={() => { selectFile(null); if (fileInput.current) fileInput.current.value = ""; }} aria-label="Clear selected file" disabled={busy}><Icon name="close"/></button></div>}
        <div className="upload-actions">{uploadState === "uploading" ? <><span className="wait-label"><Icon name="clock"/> Uploading and indexing… {formatElapsed(uploadElapsed)} elapsed</span><button className="secondary-button" type="button" onClick={stopWaiting}>Stop waiting</button></> : <button className="primary-button" type="submit" disabled={!file || busy}>{uploadState === "validating" ? "Validating PDF…" : "Upload and index"}<Icon name="arrow"/></button>}</div>
      </form>
      {uploadMessage && <div className={`upload-feedback ${uploadState === "error" ? "upload-feedback--error" : ""}`} role={uploadState === "error" || uploadState === "stopped" ? "alert" : "status"} aria-live="polite">{uploadMessage}{uploadState === "stopped" && <button type="button" className="text-button" onClick={() => void runRefresh()} disabled={refreshing}>Refresh library</button>}{uploadState === "error" && uploadMessage.includes("already indexed") && <button type="button" className="text-button" onClick={() => void runRefresh()}>Refresh library</button>}</div>}
      {uploadResult && uploadState === "success" && <div ref={uploadSuccessRef} className="upload-success" role="status" tabIndex={-1}><p><strong>Indexing confirmed.</strong> {typeof uploadResult.document.page_count === "number" ? `${uploadResult.document.page_count} pages · ` : ""}{typeof uploadResult.document.chunk_count === "number" ? `${uploadResult.document.chunk_count} chunks` : "Document indexed by the API."}</p><AppLink href="/workspace">Ask about this document <Icon name="arrow"/></AppLink></div>}
      {announcement && <p className="sr-only" role="status" aria-live="polite">{announcement}</p>}
    </section>}

    <section className="document-section" aria-labelledby="documents-heading"><div className="list-heading"><div><p className="eyebrow">INDEXED RECORDS</p><h2 id="documents-heading">Documents <span className="count-badge">{documentsError ? "—" : documents.length}</span></h2></div>{documents.length > 8 && <label className="filter-field">Filter documents<input type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Search filenames"/></label>}</div>
      {status === "loading" && <div className="loading-placeholder" role="status"><span className="loading-spinner"/> Loading documents…</div>}
      {documentsError && <div className="empty-panel error-panel" role="alert"><Icon name="attention"/><div><strong>Could not load documents</strong><p>{documentsError}</p><button className="secondary-button" onClick={() => void runRefresh()} disabled={refreshing}>Retry</button></div></div>}
      {!documentsError && status !== "loading" && documents.length === 0 && <div className="empty-panel"><span className="large-icon"><Icon name="document"/></span><div><strong>No documents indexed</strong><p>Upload a PDF to start asking questions about it.</p></div></div>}
      {!documentsError && documents.length > 0 && <>
        <div className="desktop-table-wrap"><table className="document-table"><caption className="sr-only">Indexed documents in the knowledge base</caption><thead><tr><th scope="col">Document</th><th scope="col">Status</th>{showPageCount && <th scope="col">Pages</th>}{showChunkCount && <th scope="col">Chunks</th>}{canDelete && <th scope="col"><span className="sr-only">Actions</span></th>}</tr></thead><tbody>{visibleDocuments.map((document) => <DocumentRow key={document.document_id} document={document} showPageCount={showPageCount} showChunkCount={showChunkCount} canDelete={canDelete} disabled={busy || !!deleting} setRef={(node) => { if (document.document_id) rowRefs.current[document.document_id] = node; }} onDelete={(trigger) => requestDelete(document, trigger)}/>)}</tbody></table></div>
        <div className="document-cards">{visibleDocuments.map((document) => <article className="document-card" key={document.document_id} tabIndex={-1} ref={(node) => { if (document.document_id) rowRefs.current[document.document_id] = node; }}><div className="document-card-head"><Icon name="document"/><strong title={safeFilename(document.filename)}>{safeFilename(document.filename)}</strong><StatusChip status={document.status}/></div><div className="document-meta">{typeof document.page_count === "number" && <span>{document.page_count} pages</span>}{typeof document.chunk_count === "number" && <span>{document.chunk_count} chunks</span>}</div>{canDelete && <button className="danger-button" type="button" onClick={(event) => requestDelete(document, event.currentTarget)} disabled={busy || deleting === document.document_id || !!deleting}><Icon name="trash"/>Delete</button>}</article>)}</div>
        {visibleDocuments.length === 0 && <p className="empty-filter">No documents match “{filter}”.</p>}
      </>}
      {lastUpdated && <p className="last-updated">Last updated {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(lastUpdated)}</p>}
      {deleteMessage && <p ref={deleteStatusRef} className="delete-feedback" role="status" aria-live="polite" tabIndex={-1}>{deleteMessage}</p>}
    </section>

    {canDelete && <dialog className="confirm-dialog" ref={dialogRef} aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-description" onClose={handleDialogClose} onCancel={(event) => { if (dialogBusy) { event.preventDefault(); } else { dialogRef.current?.close(); } }} onKeyDown={(event) => { if (event.key === "Escape" && !dialogBusy) { event.preventDefault(); dialogRef.current?.close(); } }}>
      <div className="dialog-icon"><Icon name="trash"/></div><h2 id="delete-dialog-title">Delete document?</h2><p id="delete-dialog-description">This removes <strong>{safeFilename(deleteTarget?.filename)}</strong> from the searchable knowledge base.</p><p>The stored PDF will also be removed when the backend can delete it.</p>{dialogMessage && <div className="dialog-error" role="alert">{dialogMessage}</div>}<div className="dialog-actions"><button ref={cancelButtonRef} type="button" className="secondary-button" onClick={() => dialogRef.current?.close()} disabled={dialogBusy}>Cancel</button><button type="button" className="danger-confirm" onClick={() => void confirmDelete()} disabled={dialogBusy || busy}>{dialogBusy ? "Deleting…" : "Delete document"}</button></div>
    </dialog>}
  </main>;
}

function DocumentRow({ document, showPageCount, showChunkCount, canDelete, disabled, setRef, onDelete }: { document: DocumentRecord; showPageCount: boolean; showChunkCount: boolean; canDelete: boolean; disabled: boolean; setRef: (node: HTMLElement | null) => void; onDelete: (trigger: HTMLElement | null) => void }) {
  return <tr ref={setRef} tabIndex={-1}><th scope="row"><span className="table-file"><Icon name="document"/><span title={safeFilename(document.filename)}>{safeFilename(document.filename)}</span></span></th><td><StatusChip status={document.status}/></td>{showPageCount && <td>{typeof document.page_count === "number" ? document.page_count : "—"}</td>}{showChunkCount && <td>{typeof document.chunk_count === "number" ? document.chunk_count : "—"}</td>}{canDelete && <td><button className="danger-button" type="button" onClick={(event) => onDelete(event.currentTarget)} disabled={disabled}><Icon name="trash"/>Delete</button></td>}</tr>;
}

function StatusChip({ status }: { status?: string | null }) {
  const supported = status || "Status not supplied";
  return <span className="status-chip"><span aria-hidden="true">{supported === "indexed" ? <Icon name="check"/> : <Icon name="clock"/>}</span>{supported}</span>;
}

function uploadErrorMessage(error: unknown) {
  if (error instanceof ApiRequestError) {
    if (error.status === 409) return "A PDF with identical content is already indexed. Review the matching document below.";
    if (error.status === 400) return `${error.message} Choose a valid PDF and try again.`;
    if (error.status === 413) return "This PDF exceeds the backend’s 25 MB upload limit. Choose a smaller file.";
    if (error.status === 422) return `The upload request was not valid: ${error.message}`;
    if ([502, 503, 504, 408].includes(error.status ?? 0)) return `${error.message} The server may still be processing; refresh the library before retrying.`;
    return error.message;
  }
  return error instanceof Error ? error.message : "The upload could not be completed. Check the connection and refresh the library.";
}

function duplicateRecord(error: unknown): DocumentRecord | undefined {
  if (!(error instanceof ApiRequestError) || error.status !== 409 || !error.detail || typeof error.detail !== "object") return;
  const existing = (error.detail as Record<string, unknown>).existing_document;
  return existing && typeof existing === "object" ? existing as DocumentRecord : undefined;
}

function safeFilename(value?: string | null): string {
  if (!value) return "Document";
  return value.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) || "Document";
}

function formatBytes(bytes: number) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatElapsed(seconds: number) { return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`; }
