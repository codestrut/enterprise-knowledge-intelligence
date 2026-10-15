import { useCallback, useEffect, useState } from "react";
import { getHealth } from "./api/client";
import type { HealthResponse } from "./api/types";
import Workspace from "./Workspace";

export default function App() {
  return window.location.pathname === "/workspace" ? <Workspace /> : <Dashboard />;
}

type HealthState =
  | { kind: "loading" }
  | { kind: "healthy"; health: HealthResponse; checkedAt: Date }
  | { kind: "unavailable"; message: string }
  | { kind: "error"; message: string };

const REFRESH_INTERVAL_MS = 30_000;

function Dashboard() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  const [refreshing, setRefreshing] = useState(false);

  const refreshHealth = useCallback(async (signal?: AbortSignal) => {
    setRefreshing(true);
    try {
      const health = await getHealth(signal);
      if (!signal?.aborted) {
        if (health.status !== "ok") {
          setState({
            kind: "error",
            message: `The API responded, but its status is ${health.status || "unknown"}.`,
          });
        } else {
          setState({ kind: "healthy", health, checkedAt: new Date() });
        }
      }
    } catch (error) {
      if (signal?.aborted) return;
      const message =
        error instanceof Error ? error.message : "An unexpected API error occurred.";
      setState({
        kind: error instanceof TypeError ? "unavailable" : "error",
        message,
      });
    } finally {
      if (!signal?.aborted) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refreshHealth(controller.signal);
    const interval = window.setInterval(
      () => void refreshHealth(),
      REFRESH_INTERVAL_MS,
    );
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refreshHealth]);

  const healthy = state.kind === "healthy" ? state.health : undefined;
  const statusClass =
    state.kind === "healthy"
      ? "status-pill status-pill--healthy"
      : state.kind === "loading"
        ? "status-pill status-pill--loading"
        : state.kind === "unavailable"
          ? "status-pill status-pill--unavailable"
          : "status-pill status-pill--error";
  const statusLabel =
    state.kind === "healthy"
      ? "Operational"
      : state.kind === "loading"
        ? "Connecting"
        : state.kind === "unavailable"
          ? "Unavailable"
          : "API error";

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="EKIP home">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </span>
          <span className="brand-name">EKIP</span>
          <span className="brand-divider" aria-hidden="true" />
          <span className="brand-caption">Knowledge intelligence</span>
        </a>
        <nav aria-label="Main navigation" className="main-nav"><a href="/" aria-current="page">System overview</a><a href="/workspace">Workspace</a></nav>
        <span className={statusClass} role="status" aria-live="polite">
          <span className="status-dot" aria-hidden="true" />
          {statusLabel}
        </span>
      </header>

      <section className="hero" id="home" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow"><span /> YOUR KNOWLEDGE, IN CONTEXT</p>
          <h1 id="hero-title">A clearer view of what your knowledge can do.</h1>
          <p className="hero-description">
            EKIP brings your organization’s information together so teams can
            find grounded answers with confidence.
          </p>
          <div className="hero-note">
            <span className="note-icon" aria-hidden="true">✳</span>
            <p>Good decisions start with a trusted source.</p>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="art-orbit art-orbit--outer" />
          <div className="art-orbit art-orbit--inner" />
          <div className="art-center"><span>EK</span><i /></div>
          <span className="art-node art-node--one">✦</span>
          <span className="art-node art-node--two">⌘</span>
          <span className="art-node art-node--three">↗</span>
          <span className="art-node art-node--four">◌</span>
          <span className="art-line art-line--one" />
          <span className="art-line art-line--two" />
        </div>
      </section>

      <section className="status-section" aria-labelledby="status-heading">
        <div className="section-heading">
          <div>
            <p className="eyebrow">SYSTEM OVERVIEW</p>
            <h2 id="status-heading">Your knowledge base</h2>
          </div>
          <button
            className="refresh-button"
            type="button"
            onClick={() => void refreshHealth()}
            disabled={refreshing}
            aria-label="Refresh API health"
          >
            <span className={refreshing ? "refresh-icon is-spinning" : "refresh-icon"} aria-hidden="true">↻</span>
            Refresh
          </button>
        </div>

        {state.kind === "loading" && (
          <div className="message-card" role="status" aria-live="polite">
            <span className="loading-spinner" aria-hidden="true" />
            <div><strong>Connecting to EKIP</strong><p>Checking the backend health endpoint…</p></div>
          </div>
        )}

        {(state.kind === "unavailable" || state.kind === "error") && (
          <div className={`message-card message-card--${state.kind}`} role="alert">
            <span className="message-symbol" aria-hidden="true">!</span>
            <div className="message-content">
              <strong>{state.kind === "unavailable" ? "Backend unavailable" : "Could not read API health"}</strong>
              <p>{state.message}</p>
              <button className="retry-button" type="button" onClick={() => void refreshHealth()}>
                Try again
              </button>
            </div>
          </div>
        )}

        {healthy && (
          <>
            <div className="metrics-grid" aria-live="polite">
              <MetricCard label="Indexed documents" value={formatCount(healthy.document_count)} icon="▤" />
              <MetricCard label="Searchable chunks" value={formatCount(healthy.chunk_count)} icon="⌕" />
              <MetricCard
                label="Documents needing attention"
                value={formatCount(healthy.failed_document_count)}
                icon="◈"
                tone={healthy.failed_document_count ? "attention" : "normal"}
              />
            </div>
            <div className="connection-row">
              <span className="connection-indicator" aria-hidden="true" />
              <span>Connected to EKIP API</span>
              <span className="connection-separator" aria-hidden="true">·</span>
              <span>Manifest {healthy.manifest_exists == null ? "status unknown" : healthy.manifest_exists ? "available" : "not created yet"}</span>
              <span className="checked-time">Updated {state.kind === "healthy" ? formatTime(state.checkedAt) : "—"}</span>
            </div>
          </>
        )}
      </section>

      <footer className="footer">
        <span>EKIP <span aria-hidden="true">·</span> Enterprise Knowledge Intelligence Platform</span>
        <a href="/workspace">Open knowledge workspace</a>
      </footer>
    </main>
  );
}

function MetricCard({
  label,
  value,
  icon,
  tone = "normal",
}: {
  label: string;
  value: string;
  icon: string;
  tone?: "normal" | "attention";
}) {
  return (
    <article className={`metric-card${tone === "attention" ? " metric-card--attention" : ""}`}>
      <div className="metric-topline"><span>{label}</span><span className="metric-icon" aria-hidden="true">{icon}</span></div>
      <strong className="metric-value">{value}</strong>
      <span className="metric-caption">Live from your knowledge base</span>
    </article>
  );
}

function formatCount(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat().format(value)
    : "—";
}

function formatTime(value: Date): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(value);
}
