import type { CurrentUserProfile, DocumentListResponse, DocumentRecord, HealthResponse, QueryCitation, QueryRequest, QueryResponse, QuerySourceMapEntry, UploadResponse, DeleteResponse } from "./types";

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const UPLOAD_TIMEOUT_MS = 5 * 60 * 1000;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;
let accessToken: string | null = null;
let refreshToken: string | null = null;
let refreshRotationKey: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;
// Incremented whenever the signed-in session changes (sign-in, sign-out, expiry). Responses to
// requests started under an earlier session are discarded and never refresh or retry.
let sessionGeneration = 0;

function sessionChanged(): DOMException {
  return new DOMException("The session changed before the response arrived.", "AbortError");
}

export function setAccessToken(token: string | null) {
  sessionGeneration += 1;
  accessToken = token;
  if (token === null) {
    refreshToken = null;
    refreshRotationKey = null;
    refreshInFlight = null;
  }
}

export class ApiRequestError extends Error {
  status?: number;
  detail?: unknown;
  constructor(message: string, status?: number, detail?: unknown) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
  }
}

async function requestJson<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, timeoutMessage = "The API request timed out. Try again shortly.", allowNoContent = false, retryAfterRefresh = true): Promise<T> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  let timedOut = false;
  const abort = () => controller.abort();
  externalSignal?.addEventListener("abort", abort, { once: true });
  if (externalSignal?.aborted) controller.abort();
  const timeout = timeoutMs === undefined ? undefined : setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const headers = new Headers(init.headers);
    const requestToken = accessToken;
    const requestGeneration = sessionGeneration;
    if (requestToken) headers.set("Authorization", `Bearer ${requestToken}`);
    const response = await fetch(path, { ...init, headers, signal: controller.signal });
    if (requestGeneration !== sessionGeneration) throw sessionChanged();
    let payload: unknown;
    const body = await response.text();
    if (body) {
      try { payload = JSON.parse(body); } catch { payload = undefined; }
    }
    if (!response.ok) {
      if (response.status === 401 && retryAfterRefresh && path !== "/api/auth/login" && path !== "/api/auth/refresh") {
        const method = (init.method ?? "GET").toUpperCase();
        const safeToRetry = ["GET", "HEAD", "OPTIONS"].includes(method) || path === "/api/query" || path === "/api/auth/logout";
        const tokenChanged = accessToken !== null && requestToken !== accessToken;
        if (safeToRetry && tokenChanged) {
          return requestJson<T>(path, init, timeoutMs, timeoutMessage, allowNoContent, false);
        }
        const refreshed = refreshToken ? await refreshSession() : false;
        if (requestGeneration !== sessionGeneration) throw sessionChanged();
        if (refreshed && safeToRetry) {
          return requestJson<T>(path, init, timeoutMs, timeoutMessage, allowNoContent, false);
        }
        if (!refreshed && !tokenChanged) {
          setAccessToken(null);
          window.dispatchEvent(new CustomEvent("ekip:auth-required"));
        }
      }
      const detail = readApiDetailValue(payload);
      throw new ApiRequestError(safeApiMessage(detail.message || httpError(response.status, path === "/api/query")), response.status, detail.raw);
    }
    if (allowNoContent && response.status === 204) return undefined as T;
    if (payload === undefined) throw new ApiRequestError("The EKIP API returned an unreadable response.", response.status);
    return payload as T;
  } catch (error) {
    if (error instanceof ApiRequestError) throw error;
    if (timedOut) throw new ApiRequestError(timeoutMessage, 408);
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    if (externalSignal?.aborted) throw new DOMException("The request was aborted", "AbortError");
    throw new TypeError("Cannot reach the EKIP API. Check that the backend is running.");
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abort);
  }
}

function makeRotationKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function refreshSession(): Promise<boolean> {
  if (!refreshToken) return false;
  if (refreshInFlight) return refreshInFlight;
  const previousToken = refreshToken;
  const rotationKey = refreshRotationKey ?? makeRotationKey();
  refreshRotationKey = rotationKey;
  const operation = (async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), DEFAULT_REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: previousToken, rotation_key: rotationKey }),
        signal: controller.signal,
      });
      const body = await response.text();
      let payload: unknown;
      if (body) {
        try { payload = JSON.parse(body); } catch { payload = undefined; }
      }
      if (refreshToken !== previousToken) return accessToken !== null;
      if (response.status === 401) return false;
      if (!response.ok) {
        const detail = readApiDetailValue(payload);
        throw new ApiRequestError(safeApiMessage(detail.message || httpError(response.status)), response.status, detail.raw);
      }
      if (!isRecord(payload) || typeof payload.access_token !== "string" || typeof payload.refresh_token !== "string") {
        throw new ApiRequestError("The EKIP API returned an invalid session refresh response.");
      }
      accessToken = payload.access_token;
      refreshToken = payload.refresh_token;
      refreshRotationKey = null;
      return true;
    } catch (error) {
      if (error instanceof ApiRequestError) throw error;
      if (error instanceof DOMException && error.name === "AbortError") {
        throw new ApiRequestError("The session refresh request timed out. Try again shortly.", 408);
      }
      throw new TypeError("Cannot reach the EKIP API to refresh this session.");
    } finally {
      clearTimeout(timeout);
    }
  })();
  refreshInFlight = operation;
  try {
    return await operation;
  } finally {
    if (refreshInFlight === operation) refreshInFlight = null;
  }
}

export interface OrganisationChoice { id: string; name: string; slug: string }
export interface OrganisationSelectionResponse {
  requires_organisation_selection: true;
  organisations: OrganisationChoice[];
}

export async function login(email: string, password: string, organisationId?: string): Promise<OrganisationSelectionResponse | void> {
  const payload = await requestJson<unknown>("/api/auth/login", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, ...(organisationId ? { organisation_id: organisationId } : {}) }),
  });
  if (!isRecord(payload)) throw new ApiRequestError("The EKIP API returned an invalid login response.");
  if (payload.requires_organisation_selection === true && Array.isArray(payload.organisations)) {
    return { requires_organisation_selection: true, organisations: payload.organisations.filter(isRecord).filter((item) => typeof item.id === "string" && typeof item.name === "string" && typeof item.slug === "string") as unknown as OrganisationChoice[] };
  }
  if (typeof payload.access_token !== "string" || typeof payload.refresh_token !== "string" || !Array.isArray(payload.permissions) || typeof payload.organisation_id !== "string" || typeof payload.role !== "string") throw new ApiRequestError("The EKIP API returned an invalid login response.");
  setAccessToken(payload.access_token);
  refreshToken = payload.refresh_token;
  refreshRotationKey = null;
}

export async function getCurrentUser(signal?: AbortSignal): Promise<CurrentUserProfile> {
  const payload = await requestJson<unknown>("/api/auth/me", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.email !== "string" || !isRecord(payload.organisation) ||
      typeof payload.organisation.id !== "string" || typeof payload.organisation.name !== "string" ||
      typeof payload.role !== "string" || !Array.isArray(payload.permissions) ||
      !payload.permissions.every((permission) => typeof permission === "string")) {
    throw new ApiRequestError("The EKIP API returned an invalid user profile.");
  }
  return payload as unknown as CurrentUserProfile;
}

export async function logout(signal?: AbortSignal): Promise<void> {
  await requestJson<void>("/api/auth/logout", { method: "POST", headers: { Accept: "application/json" }, signal }, DEFAULT_REQUEST_TIMEOUT_MS, undefined, true);
}

function httpError(status: number, isQuery = false): string {
  if ([502, 503, 504].includes(status)) return isQuery
    ? `The server took too long to respond or is unavailable (HTTP ${status}). The query may still be running. Try again shortly.`
    : `The server took too long to respond or is unavailable (HTTP ${status}). The operation may still be running. Refresh before retrying.`;
  if (status === 429) return "Too many requests (HTTP 429). Wait a moment and try again.";
  return `The EKIP API returned HTTP ${status}.`;
}

function readApiDetailValue(payload: unknown): { message?: string; raw?: unknown } {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return {};
  const detail = (payload as Record<string, unknown>).detail;
  if (typeof detail === "string") return { message: detail, raw: detail };
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return "";
      const entry = item as Record<string, unknown>;
      const loc = Array.isArray(entry.loc) ? entry.loc.filter((part) => typeof part === "string" || typeof part === "number").join(" → ") : "";
      return `${loc ? `${loc}: ` : ""}${typeof entry.msg === "string" ? entry.msg : "Invalid value"}`;
    }).filter(Boolean);
    return { message: messages.join(". ") || undefined, raw: detail };
  }
  if (detail && typeof detail === "object") {
    const value = detail as Record<string, unknown>;
    for (const key of ["message", "msg", "error", "detail"]) if (typeof value[key] === "string") return { message: value[key] as string, raw: detail };
    return { raw: detail };
  }
  return {};
}

export function readApiDetail(payload: unknown): string | undefined {
  return readApiDetailValue(payload).message;
}

function safeApiMessage(value: string): string {
  return value.replace(/(?:[A-Za-z]:\\(?:[^\\\s"'<>]+\\)*[^\\\s"'<>]+|\/(?:[^/\s"'<>]+\/)*[^/\s"'<>]+)/g, (path) => path.split(/[\\/]/).filter(Boolean).at(-1) ?? "document");
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const payload = await requestJson<unknown>("/api/health", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || !nullableNumber(payload.document_count) || !nullableNumber(payload.chunk_count) || !nullableNumber(payload.failed_document_count) ||
    (payload.status !== undefined && payload.status !== null && typeof payload.status !== "string") ||
    (payload.manifest_exists !== undefined && payload.manifest_exists !== null && typeof payload.manifest_exists !== "boolean")) {
    throw new ApiRequestError("The EKIP API returned an invalid health response.");
  }
  return payload as HealthResponse;
}

export async function getDocuments(signal?: AbortSignal): Promise<DocumentListResponse> {
  const payload = await requestJson<unknown>("/api/documents", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.documents)) throw new ApiRequestError("The EKIP API returned an invalid document list.");
  return { count: payload.count, documents: payload.documents.filter(isRecord).map((record) => record as DocumentRecord) };
}

export async function uploadDocument(file: File, signal: AbortSignal): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  const payload = await requestJson<UploadResponse>("/api/documents", { method: "POST", headers: { Accept: "application/json" }, body: form, signal }, UPLOAD_TIMEOUT_MS, "The upload request timed out. The server may still be indexing the PDF.");
  if (!isRecord(payload) || !isRecord(payload.document)) throw new ApiRequestError("The EKIP API returned an invalid upload response.");
  return payload;
}

export async function deleteDocument(documentId: string, signal?: AbortSignal): Promise<DeleteResponse> {
  const payload = await requestJson<DeleteResponse>(`/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE", headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.document_id !== "string" || typeof payload.file_deleted !== "boolean" || typeof payload.cleanup_required !== "boolean") throw new ApiRequestError("The EKIP API returned an invalid deletion response.");
  return payload;
}

export async function postQuery(request: QueryRequest, signal: AbortSignal): Promise<QueryResponse> {
  const payload = await requestJson<unknown>("/api/query", { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify(request), signal }, 120_000, "The query request timed out. The server may still be working; try again shortly.");
  if (!isRecord(payload) || typeof payload.answer !== "string") throw new ApiRequestError("The EKIP API returned an unexpected query response.");
  return normalizeQueryResponse(payload as unknown as QueryResponse);
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function nullableNumber(value: unknown): boolean { return value === undefined || value === null || (typeof value === "number" && Number.isFinite(value)); }

function normalizeQueryResponse(value: QueryResponse): QueryResponse {
  const entries = (input: unknown): Record<string, unknown>[] => Array.isArray(input) ? input.filter(isRecord) : [];
  const sources = entries(value.sources).map((source) => ({
    text: typeof source.text === "string" ? source.text : undefined,
    score: typeof source.score === "number" ? source.score : null,
    metadata: isRecord(source.metadata) ? source.metadata : {},
  }));
  const citations: QueryCitation[] = entries(value.citations).flatMap((citation) => {
    const page = citation.page;
    const chunkId = citation.chunk_id;
    if (typeof citation.source_number !== "number" || typeof citation.source !== "string" ||
      (typeof page !== "string" && typeof page !== "number") || (typeof chunkId !== "string" && typeof chunkId !== "number")) return [];
    return [{ source_number: citation.source_number, source: citation.source, page, chunk_id: chunkId }];
  });
  const grounding = entries(value.grounding).map((claim) => ({
    ...claim,
    claim: typeof claim.claim === "string" ? claim.claim : undefined,
    status: typeof claim.status === "string" ? claim.status : undefined,
    reason: typeof claim.reason === "string" ? claim.reason : undefined,
    supporting_passage: typeof claim.supporting_passage === "string" ? claim.supporting_passage : undefined,
  }));
  const sourceMap: Record<string, QuerySourceMapEntry> = {};
  if (isRecord(value.source_map)) for (const [number, rawEntry] of Object.entries(value.source_map)) {
    if (!isRecord(rawEntry)) continue;
    const { source, page, chunk_id: chunkId } = rawEntry;
    if (typeof source === "string" && (typeof page === "string" || typeof page === "number") && (typeof chunkId === "string" || typeof chunkId === "number")) sourceMap[number] = { source, page, chunk_id: chunkId };
  }
  const evidence = isRecord(value.evidence) ? {
    sufficient: typeof value.evidence.sufficient === "boolean" ? value.evidence.sufficient : undefined,
    score: typeof value.evidence.score === "number" ? value.evidence.score : null,
    threshold: typeof value.evidence.threshold === "number" ? value.evidence.threshold : undefined,
    reason: typeof value.evidence.reason === "string" ? value.evidence.reason : undefined,
  } : undefined;
  const repair = isRecord(value.generation_repair) ? {
    attempted: typeof value.generation_repair.attempted === "boolean" ? value.generation_repair.attempted : undefined,
    accepted: typeof value.generation_repair.accepted === "boolean" ? value.generation_repair.accepted : undefined,
    reason: typeof value.generation_repair.reason === "string" ? value.generation_repair.reason : undefined,
    mode: typeof value.generation_repair.mode === "string" ? value.generation_repair.mode : undefined,
    initial_issue_count: typeof value.generation_repair.initial_issue_count === "number" ? value.generation_repair.initial_issue_count : undefined,
    grounded_subset_used: typeof value.generation_repair.grounded_subset_used === "boolean" ? value.generation_repair.grounded_subset_used : undefined,
    grounded_subset_claim_count: typeof value.generation_repair.grounded_subset_claim_count === "number" ? value.generation_repair.grounded_subset_claim_count : undefined,
    initial_diagnostics: isRecord(value.generation_repair.initial_diagnostics) ? value.generation_repair.initial_diagnostics : undefined,
    repair_diagnostics: isRecord(value.generation_repair.repair_diagnostics) ? value.generation_repair.repair_diagnostics : undefined,
  } : undefined;
  return {
    answer: value.answer,
    question: typeof value.question === "string" ? value.question : undefined,
    refused: typeof value.refused === "boolean" ? value.refused : undefined,
    sources,
    citations,
    grounding,
    evidence,
    generation_repair: repair,
    invalid_citations: Array.isArray(value.invalid_citations) ? value.invalid_citations.filter((item): item is number => typeof item === "number") : [],
    source_map: sourceMap,
  };
}
