import { useEffect, useMemo, useRef, useState } from "react";
import { postQuery } from "./api/client";
import type { QueryCitation, QueryResponse, QuerySource, QuerySourceMapEntry } from "./api/types";
import { AppLink } from "./AppShell";
import { useKnowledgeBase } from "./KnowledgeBaseContext";
import { Icon } from "./Icons";

const REQUEST_TIMEOUT_MS = 120_000;
const SOURCE_REF = /\[Source\s+(\d+)\]/g;

type RequestState = "idle" | "loading" | "success" | "error" | "cancelled" | "timeout";

export default function Workspace() {
  const knowledgeBase = useKnowledgeBase();
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(5);
  const [state, setState] = useState<RequestState>("idle");
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [copyMessage, setCopyMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  const timedOut = useRef(false);
  const answerHeading = useRef<HTMLHeadingElement>(null);
  const sourceRefs = useRef<Record<number, HTMLElement | null>>({});

  // Abandon an in-flight query when the workspace unmounts (for example on sign-out).
  useEffect(() => () => controller.current?.abort(), []);

  useEffect(() => {
    if (state !== "loading") return;
    const timer = window.setInterval(() => setElapsed((time) => time + 1), 1000);
    return () => window.clearInterval(timer);
  }, [state]);

  const sourceLinks = useMemo(() => result ? resolveCitationSources(result) : new Map<number, { citation: QueryCitation; source: QuerySource }>(), [result]);
  const answerCitationNumbers = useMemo(() => result ? citationNumbers(result.answer) : [], [result]);
  const unmapped = answerCitationNumbers.filter((number) => !sourceLinks.has(number));
  const citedSourceNumbers = useMemo(() => new Set(answerCitationNumbers.filter((number) => sourceLinks.has(number))), [answerCitationNumbers, sourceLinks]);
  const refused = result?.refused === true || result?.evidence?.sufficient === false;
  const documentCount = typeof knowledgeBase.health?.document_count === "number" ? knowledgeBase.health.document_count : knowledgeBase.documents.length;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (controller.current || !question.trim()) return;
    const currentController = new AbortController();
    controller.current = currentController;
    timedOut.current = false;
    setResult(null);
    setErrorMessage("");
    setCopyMessage("");
    setElapsed(0);
    setState("loading");
    const timeout = window.setTimeout(() => {
      timedOut.current = true;
      currentController.abort();
    }, REQUEST_TIMEOUT_MS);
    try {
      const response = await postQuery({ question: question.trim(), top_k: topK }, currentController.signal);
      setResult(response);
      setState("success");
      window.requestAnimationFrame(() => answerHeading.current?.focus());
    } catch (error) {
      if (currentController.signal.aborted) {
        setState(timedOut.current ? "timeout" : "cancelled");
        setErrorMessage(timedOut.current
          ? "The browser stopped waiting after 120 seconds. The server may still be processing this query. You can try again."
          : "You stopped waiting for this response. The server may still be processing this query.");
      } else {
        setState("error");
        setErrorMessage(error instanceof Error ? error.message : "An unexpected error occurred. Please try again.");
      }
    } finally {
      window.clearTimeout(timeout);
      if (controller.current === currentController) controller.current = null;
    }
  }

  function cancel() {
    controller.current?.abort();
  }

  async function copyAnswer() {
    if (!result) return;
    const verifiedNumbers = [...new Set(answerCitationNumbers)].filter((number) => sourceLinks.has(number));
    const footnoteNumbers = new Map(verifiedNumbers.map((number, index) => [number, index + 1]));
    const markdownAnswer = result.answer.replace(SOURCE_REF, (reference, rawNumber: string) => {
      const footnote = footnoteNumbers.get(Number(rawNumber));
      return footnote ? `[^${footnote}]` : reference;
    });
    const footnotes = verifiedNumbers.map((number, index) => {
      const { citation, source } = sourceLinks.get(number)!;
      const page = citation.page != null ? `, p. ${citation.page}` : "";
      return `[^${index + 1}]: ${sourceName(source, citation)}${page}`;
    });
    const markdown = `${markdownAnswer}${footnotes.length ? `\n\n${footnotes.join("\n")}` : ""}`;
    try {
      await navigator.clipboard.writeText(markdown);
      setCopyMessage("Answer copied, including mapped source notes.");
    } catch {
      setCopyMessage("Could not copy the answer. Check clipboard access and try again.");
    }
  }

  function navigateToSource(number: number) {
    const target = sourceRefs.current[number];
    if (!target) return;
    target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    target.focus({ preventScroll: true });
    target.classList.add("source-card--highlighted");
    window.setTimeout(() => target.classList.remove("source-card--highlighted"), 1800);
  }

  return (
    <main className="page-section workspace-page">
      <section className="workspace-intro" aria-labelledby="workspace-title">
        <p className="eyebrow"><span /> KNOWLEDGE WORKSPACE</p>
        <h1 id="workspace-title" tabIndex={-1}>Ask your knowledge base</h1>
        <p>Get answers from the available documents, with citations and verification details you can inspect.</p>
      </section>

      {knowledgeBase.status === "available" && <div className="workspace-scope"><span>Searching {documentCount} {documentCount === 1 ? "document" : "documents"}</span>{knowledgeBase.documents.length > 0 && knowledgeBase.documents.length <= 10 && <details><summary>View documents</summary><ul>{knowledgeBase.documents.map((document, index) => <li key={document.document_id ?? index}>{safeDisplayText(documentName(document.filename))}</li>)}</ul></details>}</div>}
      {knowledgeBase.status === "available" && documentCount === 0 && <aside className="workspace-empty"><span className="large-icon"><span aria-hidden="true">i</span></span><div><strong>Answers depend on indexed documents</strong><p>Upload a PDF to give EKIP evidence to search. The question form stays available, and the API will report when it cannot support an answer.</p></div><AppLink href="/library">Upload a PDF</AppLink></aside>}
      <div className="example-questions"><p>Examples. Answers appear only if your documents cover them.</p><div>{["What are the main requirements?", "Summarize the key risks.", "Which steps should be completed first?"].map((example) => <button key={example} type="button" className="example-chip" onClick={() => { setQuestion(example); document.getElementById("question")?.focus(); }}>{example}</button>)}</div></div>

      <form className="question-panel" onSubmit={(event) => void submit(event)}>
        <label htmlFor="question">Your question</label>
        <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} required placeholder="Ask a question about the available documents…" disabled={state === "loading"} />
        <details className="advanced-control">
          <summary>Advanced</summary>
          <label htmlFor="top-k">Retrieved passages <span>Choose 1 to 20 (default 5)</span></label>
          <input id="top-k" type="number" min={1} max={20} value={topK} onChange={(event) => setTopK(clampTopK(event.target.value))} disabled={state === "loading"} />
        </details>
        <div className="submit-row">
          <span className="form-hint">Answers are limited to evidence in your available documents.</span>
          {state === "loading" ? <button type="button" className="secondary-button" onClick={cancel}>Stop waiting</button> : <button className="primary-button" type="submit" disabled={!question.trim()}>Ask EKIP <Icon name="arrow"/></button>}
        </div>
      </form>

      <div className="query-live" role="status" aria-live="polite" aria-atomic="true">
        {state === "loading" && <span><span className="loading-spinner" aria-hidden="true" /> Searching and checking evidence… {elapsed >= 10 && <span>{formatElapsed(elapsed)} elapsed</span>}</span>}
        {state === "cancelled" && <p>{errorMessage} Aborting the browser request does not necessarily stop server-side work.</p>}
        {state === "timeout" && <p>{errorMessage}</p>}
      </div>
      {state === "error" && <div className="query-error" role="alert"><strong>We couldn’t complete that query</strong><p>{errorMessage}</p><button type="button" className="secondary-button" onClick={() => document.getElementById("question")?.closest("form")?.requestSubmit()}>Try again</button></div>}

      {result && state === "success" && <section className="answer-layout" aria-label="Query result">
        <article className={`answer-panel${refused ? " answer-panel--refused" : ""}`}>
          <div className="answer-heading-row"><div><p className="eyebrow">{refused ? "EVIDENCE CHECK" : "EKIP ANSWER"}</p><h2 ref={answerHeading} tabIndex={-1}>{refused ? "A sufficient answer wasn’t available" : "Answer"}</h2></div>{result.answer.trim() && <button className="secondary-button copy-button" type="button" onClick={() => void copyAnswer()}>Copy answer</button>}</div>
          {refused && <p className="refusal-summary">The available documents did not support a sufficient answer to this question.</p>}
          <div className="answer-copy">{result.answer.trim() ? renderCitations(result.answer, sourceLinks, navigateToSource) : <p className="empty-answer">The API returned no answer text. You can try the question again.</p>}</div>
          {refused && <p className="rephrase-guidance">You could try asking about a specific topic covered by your documents, or add a relevant document. Rephrasing may help clarify a question, but does not guarantee that supporting evidence is available.</p>}
          {unmapped.length > 0 && <p className="citation-warning" role="status">Some citation references could not be matched to a returned source: {unmapped.map((number) => `[Source ${number}]`).join(", ")}.</p>}
          <p className="copy-feedback" role="status" aria-live="polite">{copyMessage}</p>
          <VerificationSummary claims={result.grounding ?? []} />
          <details className="diagnostics-details"><summary>How this was checked</summary><div className="diagnostics-content">
            {result.evidence && <div><h3>Evidence sufficiency</h3><p>{result.evidence.sufficient === true ? "The evidence gate allowed generation to proceed." : result.evidence.sufficient === false ? "The evidence gate did not allow generation to proceed." : "No evidence-gate result was returned."}</p>{result.evidence.reason && <p>{safeDisplayText(result.evidence.reason)}</p>}{typeof result.evidence.score === "number" && <p>Backend evidence score: {result.evidence.score}{typeof result.evidence.threshold === "number" ? ` (threshold ${result.evidence.threshold})` : ""}. This is a backend relevance score, not a probability.</p>}</div>}
            {result.generation_repair && <div><h3>Generation repair</h3><p>{result.generation_repair.attempted ? `Repair attempted${result.generation_repair.accepted ? " and accepted" : " but not accepted"}.` : "No repair was needed."}</p>{result.generation_repair.mode && <p>Mode: {safeDisplayText(result.generation_repair.mode)}</p>}{result.generation_repair.reason && <p>{safeDisplayText(result.generation_repair.reason)}</p>}{result.generation_repair.initial_issue_count != null && <p>Initial issue count: {result.generation_repair.initial_issue_count}</p>}</div>}
            {!!result.invalid_citations?.length && <div><h3>Citation validation</h3><p>The API reported invalid citation references: {result.invalid_citations.map((number) => `[Source ${number}]`).join(", ")}.</p></div>}
            {!result.evidence && !result.generation_repair && !result.invalid_citations?.length && <p>No additional check details were returned.</p>}
          </div></details>
        </article>
        {result.sources?.length ? <section className="sources-panel" aria-labelledby="sources-title"><div className="sources-heading"><p className="eyebrow">{refused ? "EVIDENCE CHECK" : "ANSWER SOURCES"}</p><h2 id="sources-title">{refused ? "Passages insufficient to support an answer" : "Sources cited in the answer"}</h2>{refused && <p>These passages were retrieved, but they did not pass the evidence check. They are not verified evidence for an answer.</p>}</div>
          {result.sources.some((_source, index) => citedSourceNumbers.has(index + 1))
            ? <div className="source-list">{result.sources.map((source, index) => { const number = index + 1; if (!citedSourceNumbers.has(number)) return null; const citation = sourceLinks.get(number)?.citation; const title = sourceName(source, citation); return <SourceCard key={`${number}-${title}`} source={source} number={number} citation={citation} registerSource={(node) => { sourceRefs.current[number] = node; }} />; })}</div>
            : <p className="uncited-empty">No retrieved passage is cited by this answer.</p>}
          {result.sources.some((_source, index) => !citedSourceNumbers.has(index + 1)) && <details className="uncited-sources"><summary>Retrieved, not cited ({result.sources.filter((_source, index) => !citedSourceNumbers.has(index + 1)).length})</summary><div className="source-list">{result.sources.map((source, index) => { const number = index + 1; if (citedSourceNumbers.has(number)) return null; const title = sourceName(source); return <SourceCard key={`${number}-${title}`} source={source} number={number} registerSource={(node) => { sourceRefs.current[number] = node; }} />; })}</div></details>}
        </section> : null}
      </section>}
    </main>
  );
}

export function resolveCitationSources(result: QueryResponse): Map<number, { citation: QueryCitation; source: QuerySource }> {
  const mapped = new Map<number, { citation: QueryCitation; source: QuerySource }>();
  const rejectedNumbers = new Set<number>();
  for (const citation of result.citations ?? []) {
    const number = citation.source_number;
    if (!Number.isSafeInteger(number) || (number as number) < 1) continue;
    if (rejectedNumbers.has(number as number)) continue;
    const sourceMap = result.source_map;
    const mapKey = String(number);
    if (!sourceMap || !Object.hasOwn(sourceMap, mapKey)) {
      rejectCitationNumber(number as number, mapped, rejectedNumbers);
      continue;
    }
    const sourceMapEntry = sourceMap[mapKey];
    if (
      !sourceMapEntry || typeof sourceMapEntry.source !== "string" || typeof citation.source !== "string" ||
      (typeof sourceMapEntry.page !== "string" && typeof sourceMapEntry.page !== "number") ||
      (typeof citation.page !== "string" && typeof citation.page !== "number") ||
      (typeof sourceMapEntry.chunk_id !== "string" && typeof sourceMapEntry.chunk_id !== "number") ||
      (typeof citation.chunk_id !== "string" && typeof citation.chunk_id !== "number")
    ) {
      rejectCitationNumber(number as number, mapped, rejectedNumbers);
      continue;
    }
    const source = result.sources?.[(number as number) - 1];
    if (!source) {
      rejectCitationNumber(number as number, mapped, rejectedNumbers);
      continue;
    }
    const metadata = source.metadata ?? {};
    if (!metadataValuesAgree(citation, sourceMapEntry, metadata)) {
      rejectCitationNumber(number as number, mapped, rejectedNumbers);
      continue;
    }
    mapped.set(number as number, { citation, source });
  }
  return mapped;
}

function rejectCitationNumber(
  number: number,
  mapped: Map<number, { citation: QueryCitation; source: QuerySource }>,
  rejectedNumbers: Set<number>,
): void {
  mapped.delete(number);
  rejectedNumbers.add(number);
}

function metadataValuesAgree(
  citation: QueryCitation,
  sourceMapEntry: QuerySourceMapEntry,
  sourceMetadata: QuerySource["metadata"],
): boolean {
  const fields = ["source", "page", "chunk_id"] as const;
  return fields.every((field) => {
    const values = [citation[field], sourceMapEntry[field], sourceMetadata?.[field]]
      .filter((value) => value !== undefined && value !== null);
    return values.every((value) => Object.is(value, values[0]));
  });
}

function citationNumbers(answer: string): number[] {
  return [...answer.matchAll(SOURCE_REF)].map((match) => Number(match[1]));
}

function renderCitations(answer: string, map: Map<number, { citation: QueryCitation; source: QuerySource }>, onSelect: (number: number) => void) {
  const pieces: React.ReactNode[] = [];
  let lastIndex = 0;
  for (const match of answer.matchAll(SOURCE_REF)) {
    const index = match.index ?? 0;
    const number = Number(match[1]);
    if (index > lastIndex) pieces.push(safeDisplayText(answer.slice(lastIndex, index)));
    pieces.push(map.has(number)
      ? <button className="citation-link" type="button" key={`${index}-${number}`} onClick={() => onSelect(number)} aria-label={`Go to Source ${number}`}>[Source {number}]</button>
      : <span className="invalid-citation" key={`${index}-${number}`}>[Source {number}]</span>);
    lastIndex = index + match[0].length;
  }
  if (!pieces.length) return safeDisplayText(answer);
  if (lastIndex < answer.length) pieces.push(safeDisplayText(answer.slice(lastIndex)));
  return pieces.map((piece, index) => <span key={index}>{piece}</span>);
}

function VerificationSummary({ claims }: { claims: QueryResponse["grounding"] }) {
  if (!claims?.length) return null;
  const grounded = claims.filter((claim) => claim.status === "grounded").length;
  return <section className="verification-section"><div className="verification-heading"><h3>Claim verification</h3><span>{grounded} of {claims.length} claims marked grounded</span></div><ClaimStatusLegend /><ul className="claim-list">{claims.map((claim, index) => <li key={`${index}-${claim.claim ?? "claim"}`}><StatusIcon status={claim.status} /><div><strong>{safeDisplayText(claim.status || "Status not provided")}</strong>{claim.claim && <p>{safeDisplayText(claim.claim)}</p>}{claim.reason && <p>{safeDisplayText(claim.reason)}</p>}<ReturnedPassages claim={claim} /></div></li>)}</ul></section>;
}

function ReturnedPassages({ claim }: { claim: NonNullable<QueryResponse["grounding"]>[number] }) {
  const passages = groundingPassages(claim);
  return passages.length ? <ul className="grounding-passages">{passages.map((passage, index) => <li key={index}><blockquote>{passage}</blockquote></li>)}</ul> : null;
}

function SourceCard({
  source,
  number,
  citation,
  registerSource,
}: {
  source: QuerySource;
  number: number;
  citation?: QueryCitation;
  registerSource: (node: HTMLElement | null) => void;
}) {
  const metadata = source.metadata ?? {};
  const title = sourceName(source, citation);
  const page = citation?.page ?? metadata.page;
  return <article className="source-card" id={`source-${number}`} aria-label={`Source ${number}: ${title}`} tabIndex={-1} ref={registerSource}><div className="source-card-top"><span className="source-number">Source {number}</span>{page != null && <span className="page-label">Page {String(page)}</span>}</div><h3>{title}</h3><p className="source-excerpt">{source.text ? safeDisplayText(source.text) : "No passage text was returned."}</p></article>;
}

function clampTopK(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 1;
  return Math.max(1, Math.min(20, Math.floor(parsed) || 1));
}

function safeDisplayText(value: string): string {
  return value.replace(/(?:[A-Za-z]:\\(?:[^\\\s"'<>]+\\)*[^\\\s"'<>]+|\/(?:[^/\s"'<>]+\/)*[^/\s"'<>]+)/g, (path) => path.split(/[\\/]/).filter(Boolean).at(-1) ?? "document");
}

function groundingPassages(claim: Record<string, unknown>): string[] {
  const passages: string[] = [];
  const isPassageText = (value: unknown): value is string => {
    if (typeof value !== "string" || !value.trim()) return false;
    const text = value.trim();
    return !/^(?:\/|\\|[A-Za-z]:[\\/])/.test(text);
  };
  if (claim.status === "grounded" && Array.isArray(claim.atomic_claims)) {
    for (const atomicClaim of claim.atomic_claims) {
      if (!atomicClaim || typeof atomicClaim !== "object") continue;
      const sources = (atomicClaim as Record<string, unknown>).sources;
      if (!Array.isArray(sources)) continue;
      for (const source of sources) {
        if (!source || typeof source !== "object") continue;
        const evidence = (source as Record<string, unknown>).evidence;
        if (!Array.isArray(evidence)) continue;
        for (const item of evidence) {
          if (!item || typeof item !== "object") continue;
          const text = (item as Record<string, unknown>).evidence;
          if (isPassageText(text)) passages.push(safeDisplayText(text.trim()));
        }
      }
    }
  }
  if (claim.status === "grounded" && isPassageText(claim.supporting_passage)) passages.unshift(safeDisplayText(claim.supporting_passage.trim()));
  return [...new Set(passages)].slice(0, 3);
}

function StatusIcon({ status }: { status?: string }) {
  const icons: Record<string, "check" | "attention" | "close" | "workspace"> = { grounded: "check", unsupported: "attention", contradicted: "close", uncited: "workspace" };
  return <span className={`claim-status claim-status--${status ?? "unknown"}`} aria-hidden="true"><Icon name={icons[status ?? ""] ?? "workspace"}/></span>;
}

function ClaimStatusLegend() {
  return <p className="claim-status-legend"><strong>Status guide:</strong> grounded = supported by the cited passage; unsupported = no sufficient support found; contradicted = evidence conflicts with the claim; uncited = no citation was provided, so the claim is not verified.</p>;
}

function sourceName(source: QuerySource, citation?: QueryCitation): string {
  const metadata = source.metadata ?? {};
  if (typeof metadata.filename === "string" && metadata.filename.trim()) return documentName(metadata.filename);
  const value = typeof metadata.source === "string" ? metadata.source : citation?.source;
  return typeof value === "string" && !value.includes("/") && !value.includes("\\")
    ? documentName(value)
    : "Retrieved document";
}

function documentName(value?: string): string {
  if (!value) return "Source";
  const safe = value.replaceAll("\\", "/").split("/").filter(Boolean).at(-1) ?? "Source";
  return safe === ".." || safe === "." ? "Source" : safe;
}

function formatElapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
