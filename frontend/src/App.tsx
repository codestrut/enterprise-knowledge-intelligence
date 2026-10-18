import { useEffect, useLayoutEffect, useState } from "react";
import AppShell, { AppLink } from "./AppShell";
import { Icon } from "./Icons";
import { KnowledgeBaseProvider, useKnowledgeBase } from "./KnowledgeBaseContext";
import DocumentLibrary from "./DocumentLibrary";
import Workspace from "./Workspace";
import { AuthProvider, useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";

export default function App() {
  return <AuthProvider><KnowledgeBaseProvider><RoutedApp /></KnowledgeBaseProvider></AuthProvider>;
}

function RoutedApp() {
  const [path, setPath] = useState(window.location.pathname);
  const kb = useKnowledgeBase();
  const auth = useAuth();
  useEffect(() => {
    const update = () => setPath(window.location.pathname);
    window.addEventListener("popstate", update);
    window.addEventListener("ekip:navigate", update);
    return () => { window.removeEventListener("popstate", update); window.removeEventListener("ekip:navigate", update); };
  }, []);
  useLayoutEffect(() => {
    const titles: Record<string, string> = { "/": "System Overview", "/library": "Document Management", "/workspace": "Knowledge Workspace" };
    document.title = `${titles[path] ?? "Page not found"} · EKIP`;
    document.querySelector<HTMLElement>("main h1")?.focus({ preventScroll: true });
  }, [path]);

  if (auth.status === "unknown") return <main className="auth-pending" aria-busy="true"><p role="status">Checking your session…</p></main>;
  if (auth.status === "signedOut") return <LoginPage/>;

  const confirmedHealth = kb.healthError ? null : kb.health;
  if (path === "/") return <AppShell active="overview" health={confirmedHealth}><Dashboard/></AppShell>;
  if (path === "/library") return <AppShell active="library" health={confirmedHealth}><DocumentLibrary/></AppShell>;
  if (path === "/workspace") return <AppShell active="workspace" health={confirmedHealth}><Workspace/></AppShell>;
  return <AppShell active="" health={confirmedHealth}><main className="page-section"><p className="eyebrow">404 · PAGE NOT FOUND</p><h1 tabIndex={-1}>This page isn’t here</h1><p>Use the main navigation or return to the system overview.</p><AppLink className="primary-button" href="/">Go to system overview <Icon name="arrow"/></AppLink></main></AppShell>;
}

function Dashboard() {
  const { health, healthError, documents, status, refreshing, lastUpdated, refresh } = useKnowledgeBase();
  const indexedCount = typeof health?.document_count === "number" ? health.document_count : documents.length;
  const chunkCount = health?.chunk_count;
  const failures = health?.failed_document_count;
  const apiConnected = !healthError && health !== null;
  const empty = indexedCount === 0;
  return <main className="page-section dashboard-page">
    <section className="compact-heading"><div><p className="eyebrow">SYSTEM OVERVIEW</p><h1 tabIndex={-1}>Knowledge operations</h1><p>Monitor indexed documents and move directly to document management or grounded search.</p></div><button className="secondary-button" type="button" onClick={() => void refresh()} disabled={refreshing}><Icon name="refresh"/>{refreshing ? "Refreshing" : "Refresh status"}</button></section>
    <div className="operational-signals"><div className={`signal-card ${apiConnected ? "signal-card--good" : "signal-card--quiet"}`}><span className="signal-dot" aria-hidden="true"/><div><strong>API connectivity</strong><p>{status === "loading" ? "Checking the API…" : apiConnected ? health.status === "ok" ? "API connected" : `API reachable; status ${health.status || "unknown"}` : "Connection status unavailable"}</p></div></div><div className={`signal-card ${empty ? "signal-card--quiet" : "signal-card--good"}`}><Icon name="library"/><div><strong>Knowledge base</strong><p>{status === "loading" ? "Loading document state…" : status === "unavailable" ? "Knowledge-base state unavailable" : empty ? "No documents indexed" : `${indexedCount.toLocaleString()} documents indexed`}</p></div></div></div>
    {status === "unavailable" && <div role="alert" className="inline-error">Could not load operational status. <button className="text-button" onClick={() => void refresh()}>Try again</button></div>}
    <div className="metrics-grid dashboard-metrics"><MetricCard label="Indexed documents" value={showCount(indexedCount, status)} icon="document" detail={empty && status === "available" ? <AppLink href="/library">Upload a PDF <Icon name="arrow"/></AppLink> : "Available to search"}/><MetricCard label="Searchable chunks" value={showCount(chunkCount, status)} icon="chunks" detail="Indexed passages"/>{typeof failures === "number" && <MetricCard label="Documents needing attention" value={failures.toLocaleString()} icon="attention" detail="Failed restore records" tone={failures > 0 ? "attention" : "normal"}/>}</div>
    <section className="first-run-card"><div><p className="eyebrow">GETTING STARTED</p><h2>First-use checklist</h2></div><ol className="checklist"><li className={indexedCount > 0 && status === "available" ? "is-complete" : ""}><span className="check-icon"><Icon name={indexedCount > 0 && status === "available" ? "check" : "document"}/></span><div><strong>Upload a PDF</strong><p>{indexedCount > 0 ? "An indexed document is available." : "Add a document before exploring grounded answers."}</p></div><AppLink href="/library">{indexedCount > 0 ? "Manage documents" : "Upload PDF"}</AppLink></li><li><span className="check-icon"><Icon name="workspace"/></span><div><strong>Ask a question</strong><p>Question activity is not persisted as checklist state.</p></div><AppLink href="/workspace">Open workspace</AppLink></li><li><span className="check-icon"><Icon name="check"/></span><div><strong>Review the citations</strong><p>Citation review is not tracked, so this stays incomplete.</p></div><AppLink href="/workspace">Review an answer</AppLink></li></ol></section>
    <div className="dashboard-meta">{lastUpdated ? <>Status updated {new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(lastUpdated)}</> : "Status update time unavailable"}</div>
  </main>;
}

function MetricCard({ label, value, icon, detail, tone = "normal" }: { label: string; value: string; icon: "document" | "chunks" | "attention"; detail: React.ReactNode; tone?: "normal" | "attention" }) {
  return <article className={`metric-card${tone === "attention" ? " metric-card--attention" : ""}`}><div className="metric-topline"><span>{label}</span><span className="metric-icon"><Icon name={icon}/></span></div><strong className="metric-value">{value}</strong><span className="metric-caption">{detail}</span></article>;
}

function showCount(value: number | null | undefined, status: string) { return status === "loading" || status === "unavailable" || typeof value !== "number" ? "—" : value.toLocaleString(); }
