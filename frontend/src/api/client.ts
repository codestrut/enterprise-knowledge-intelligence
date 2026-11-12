import type { CurrentUserProfile, DocumentListResponse, DocumentRecord, HealthResponse, QueryCitation, QueryRequest, QueryResponse, QuerySourceMapEntry, UploadResponse, DeleteResponse, PlatformOrganisation, PlatformOrganisationListResponse, PlatformOverviewResponse, PlatformRole, PlatformUser, PlatformUserSearchResponse, PlatformRoleAssignmentResponse, PlatformRoleHolder, PlatformRoleHolderListResponse, PlatformAuditEvent, PlatformAuditEventListResponse, TenantAuditEvent, TenantAuditEventListResponse, TenantInvitation, TenantInvitationCreateResponse, TenantInvitationListResponse, TenantMember, TenantMemberListResponse, TenantOverviewResponse, TenantRole, TenantSettings, JsonValue } from "./types";

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
  requestId?: string;
  constructor(message: string, status?: number, detail?: unknown, requestId?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.detail = detail;
    this.requestId = requestId;
  }
}

function extractRequestId(response: Response, payload: unknown): string | undefined {
  const headerId = response.headers.get("x-request-id") || response.headers.get("X-Request-ID");
  if (headerId && headerId.trim()) return headerId.trim();
  if (isRecord(payload)) {
    if (typeof payload.request_id === "string" && payload.request_id.trim()) {
      return payload.request_id.trim();
    }
    if (typeof payload.requestId === "string" && payload.requestId.trim()) {
      return payload.requestId.trim();
    }
  }
  return undefined;
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
          const reason = requestToken ? "expired" : undefined;
          window.dispatchEvent(new CustomEvent("ekip:auth-required", { detail: reason ? { reason } : undefined }));
        }
      }
      const requestId = extractRequestId(response, payload);
      const detail = readApiDetailValue(payload);
      throw new ApiRequestError(safeApiMessage(detail.message || httpError(response.status, path === "/api/query")), response.status, detail.raw, requestId);
    }
    const requestId = extractRequestId(response, payload);
    if (allowNoContent && response.status === 204) return undefined as T;
    if (payload === undefined) throw new ApiRequestError("The EKIP API returned an unreadable response.", response.status, undefined, requestId);
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
        const requestId = extractRequestId(response, payload);
        const detail = readApiDetailValue(payload);
        throw new ApiRequestError(safeApiMessage(detail.message || httpError(response.status)), response.status, detail.raw, requestId);
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

export type AuthScope = "tenant" | "platform";

export async function login(email: string, password: string, organisationId?: string, authScope: AuthScope = "tenant"): Promise<OrganisationSelectionResponse | void> {
  const payload = await requestJson<unknown>("/api/auth/login", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, auth_scope: authScope, ...(organisationId ? { organisation_id: organisationId } : {}) }),
  });
  if (!isRecord(payload)) throw new ApiRequestError("The EKIP API returned an invalid login response.");
  if (payload.requires_organisation_selection === true && Array.isArray(payload.organisations)) {
    return { requires_organisation_selection: true, organisations: payload.organisations.filter(isRecord).filter((item) => typeof item.id === "string" && typeof item.name === "string" && typeof item.slug === "string") as unknown as OrganisationChoice[] };
  }
  if (typeof payload.access_token !== "string" || typeof payload.refresh_token !== "string" || !Array.isArray(payload.permissions) ||
      (payload.organisation_id !== null && typeof payload.organisation_id !== "string") || typeof payload.role !== "string") {
    throw new ApiRequestError("The EKIP API returned an invalid login response.");
  }
  setAccessToken(payload.access_token);
  refreshToken = payload.refresh_token;
  refreshRotationKey = null;
}

export async function getCurrentUser(signal?: AbortSignal): Promise<CurrentUserProfile> {
  const payload = await requestJson<unknown>("/api/auth/me", { headers: { Accept: "application/json" }, signal });
  const validOrganisation = payload && isRecord(payload) && (payload.organisation === null ||
    (isRecord(payload.organisation) && typeof payload.organisation.id === "string" && typeof payload.organisation.name === "string"));
  if (!isRecord(payload) || typeof payload.email !== "string" || !validOrganisation ||
      typeof payload.role !== "string" || !Array.isArray(payload.permissions) ||
      !payload.permissions.every((permission) => typeof permission === "string")) {
    throw new ApiRequestError("The EKIP API returned an invalid user profile.");
  }
  if (payload.platform_permissions !== undefined && (!Array.isArray(payload.platform_permissions) || !payload.platform_permissions.every((permission) => typeof permission === "string"))) throw new ApiRequestError("The EKIP API returned an invalid platform permission list.");
  return { ...(payload as unknown as CurrentUserProfile), platform_permissions: Array.isArray(payload.platform_permissions) ? payload.platform_permissions as string[] : [] };
}

export async function getPlatformOrganisations(signal?: AbortSignal): Promise<PlatformOrganisationListResponse> {
  const payload = await requestJson<unknown>("/api/platform/organisations", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.organisations)) throw new ApiRequestError("The EKIP API returned an invalid platform organisation list.");
  const organisations: PlatformOrganisation[] = payload.organisations.filter(isRecord).flatMap((item) => {
    if (typeof item.id !== "string" || typeof item.name !== "string" || typeof item.slug !== "string" || typeof item.status !== "string") return [];
    return [{ id: item.id, name: item.name, slug: item.slug, status: item.status, is_active: item.is_active === true, initial_admin_email: typeof item.initial_admin_email === "string" ? item.initial_admin_email : null, provisioning_attempts: typeof item.provisioning_attempts === "number" ? item.provisioning_attempts : 0, provisioning_started_at: typeof item.provisioning_started_at === "string" ? item.provisioning_started_at : null, provisioning_error_code: typeof item.provisioning_error_code === "string" ? item.provisioning_error_code : null, created_at: typeof item.created_at === "string" ? item.created_at : null }];
  });
  return { count: payload.count, organisations };
}

export async function getPlatformOverview(signal?: AbortSignal): Promise<PlatformOverviewResponse> {
  const payload = await requestJson<unknown>("/api/platform/overview", { headers: { Accept: "application/json" }, signal });
  const fields: (keyof PlatformOverviewResponse)[] = [
    "total_tenants", "active_tenants", "pending_tenants", "provisioning_tenants",
    "failed_tenants", "suspended_tenants", "total_documents", "total_chunks",
  ];
  if (!isRecord(payload) || !fields.every((field) => typeof payload[field] === "number" && Number.isFinite(payload[field]) && (payload[field] as number) >= 0)) {
    throw new ApiRequestError("The EKIP API returned an invalid platform overview.");
  }
  return Object.fromEntries(fields.map((field) => [field, payload[field]])) as unknown as PlatformOverviewResponse;
}

export async function getPlatformRoleHolders(signal?: AbortSignal): Promise<PlatformRoleHolderListResponse> {
  const payload = await requestJson<unknown>("/api/platform/users/roles", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.assignments)) {
    throw new ApiRequestError("The EKIP API returned an invalid platform role-holder list.");
  }
  const assignments: PlatformRoleHolder[] = payload.assignments.flatMap((item): PlatformRoleHolder[] => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.user_id !== "string" ||
        typeof item.email !== "string" || !isPlatformRole(item.role) || typeof item.assigned_at !== "string") return [];
    return [{ id: item.id, user_id: item.user_id, email: item.email, role: item.role, assigned_at: item.assigned_at }];
  });
  return { count: payload.count, assignments };
}

export async function revokePlatformRole(userId: string, role: PlatformRole): Promise<void> {
  if (!userId.trim()) throw new ApiRequestError("A platform user is required.");
  await requestJson<unknown>(`/api/platform/users/${encodeURIComponent(userId)}/roles/${encodeURIComponent(role)}`, {
    method: "DELETE", headers: { Accept: "application/json" },
  });
}

export async function getPlatformAuditEvents(options: { limit?: number; before?: string } = {}, signal?: AbortSignal): Promise<PlatformAuditEventListResponse> {
  const limit = options.limit ?? 100;
  if (!Number.isInteger(limit) || limit < 1 || limit > 250) throw new ApiRequestError("Platform audit limit must be between 1 and 250.");
  const params = new URLSearchParams({ limit: String(limit) });
  if (options.before) params.set("before", options.before);
  const payload = await requestJson<unknown>(`/api/platform/audit/events?${params.toString()}`, { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.events)) {
    throw new ApiRequestError("The EKIP API returned an invalid platform audit log.");
  }
  const events: PlatformAuditEvent[] = payload.events.flatMap((item): PlatformAuditEvent[] => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.event_type !== "string" || typeof item.occurred_at !== "string" ||
        (item.actor_user_id !== null && typeof item.actor_user_id !== "string") ||
        (item.organisation_id !== null && typeof item.organisation_id !== "string") ||
        (item.target_type !== null && typeof item.target_type !== "string") ||
        (item.target_id !== null && typeof item.target_id !== "string") || !isRecord(item.details)) return [];
    const safeDetails: Record<string, JsonValue> = {};
    for (const [key, value] of Object.entries(item.details)) {
      if (PLATFORM_AUDIT_DETAIL_KEYS.has(key) && (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean")) {
        safeDetails[key] = value;
      }
    }
    return [{
      id: item.id, actor_user_id: item.actor_user_id as string | null,
      organisation_id: item.organisation_id as string | null, event_type: item.event_type,
      target_type: item.target_type as string | null, target_id: item.target_id as string | null,
      occurred_at: item.occurred_at, details: safeDetails,
    }];
  });
  return { count: payload.count, events };
}

export async function suspendPlatformOrganisation(id: string, reasonCode: string): Promise<void> {
  const reason = reasonCode.trim();
  if (!id.trim() || !reason) throw new ApiRequestError("An organisation and reason code are required.");
  await requestJson<unknown>(`/api/platform/organisations/${encodeURIComponent(id)}/suspend`, {
    method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ reason_code: reason }),
  });
}

export async function reactivatePlatformOrganisation(id: string, reasonCode: string): Promise<void> {
  const reason = reasonCode.trim();
  if (!id.trim() || !reason) throw new ApiRequestError("An organisation and reason code are required.");
  await requestJson<unknown>(`/api/platform/organisations/${encodeURIComponent(id)}/reactivate`, {
    method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ reason_code: reason }),
  });
}

function isPlatformRole(value: unknown): value is PlatformRole {
  return value === "platform_super_administrator" || value === "platform_tenant_creator" ||
    value === "platform_tenant_approver" || value === "platform_provisioning_operator";
}

const PLATFORM_AUDIT_DETAIL_KEYS = new Set([
  "action", "outcome", "reason_code", "role", "session_count", "attempt",
  "allowed_domain_count", "session_idle_timeout_minutes", "provisioning_attempts",
]);

export async function createPlatformOrganisation(input: { name: string; slug: string; initial_admin_email: string }, idempotencyKey: string): Promise<void> {
  await requestJson<unknown>("/api/platform/organisations", { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json", "Idempotency-Key": idempotencyKey }, body: JSON.stringify(input) });
}

export async function searchPlatformUsers(
  query: string,
  limit = 25,
): Promise<PlatformUserSearchResponse> {
  const needle = query.trim();
  if (needle.length < 2) {
    throw new ApiRequestError("Enter at least two characters of an email address.");
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new ApiRequestError("User search limit must be between 1 and 50.");
  }

  const params = new URLSearchParams({ q: needle, limit: String(limit) });
  const payload = await requestJson<unknown>(
    `/api/platform/users?${params.toString()}`,
    { headers: { Accept: "application/json" } },
  );

  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.users)) {
    throw new ApiRequestError("The EKIP API returned an invalid platform user list.");
  }

  const users: PlatformUser[] = payload.users.flatMap((item): PlatformUser[] => {
    if (
      !isRecord(item)
      || typeof item.id !== "string"
      || typeof item.email !== "string"
      || typeof item.is_active !== "boolean"
    ) return [];
    return [{ id: item.id, email: item.email, is_active: item.is_active }];
  });

  return { count: payload.count, users };
}

export async function assignPlatformRole(
  userId: string,
  role: PlatformRole,
): Promise<PlatformRoleAssignmentResponse> {
  const payload = await requestJson<unknown>("/api/platform/users/roles", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, role }),
  });

  if (
    !isRecord(payload)
    || typeof payload.user_id !== "string"
    || typeof payload.role !== "string"
    || typeof payload.already_assigned !== "boolean"
  ) {
    throw new ApiRequestError("The EKIP API returned an invalid platform role assignment response.");
  }

  return {
    user_id: payload.user_id,
    role: payload.role as PlatformRole,
    already_assigned: payload.already_assigned,
  };
}

export async function approvePlatformOrganisation(id: string, approvalReason: string): Promise<void> {
  await requestJson<unknown>(`/api/platform/organisations/${encodeURIComponent(id)}/approve-provisioning`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ approval_reason: approvalReason }) });
}

export async function retryPlatformProvisioning(id: string, reason: string): Promise<void> {
  await requestJson<unknown>(`/api/platform/organisations/${encodeURIComponent(id)}/provisioning/retry`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ retry_scope: "tenant", reason }) });
}

export async function recoverPlatformProvisioning(id: string, reason: string): Promise<void> {
  await requestJson<unknown>(`/api/platform/organisations/${encodeURIComponent(id)}/provisioning/recover`, { method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" }, body: JSON.stringify({ reason }) });
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

// Tenant administration API. Every request is scoped by the authenticated tenant context;
// the client deliberately does not accept an organisation ID for these operations.
export async function getTenantOverview(signal?: AbortSignal): Promise<TenantOverviewResponse> {
  const payload = await requestJson<unknown>("/api/tenant/overview", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.organisation_id !== "string" || typeof payload.organisation_name !== "string" ||
      ![payload.document_count, payload.chunk_count, payload.failed_document_count, payload.member_count].every((value) => typeof value === "number")) {
    throw new ApiRequestError("The EKIP API returned an invalid tenant overview.");
  }
  return payload as unknown as TenantOverviewResponse;
}

export async function getTenantMembers(signal?: AbortSignal): Promise<TenantMemberListResponse> {
  const payload = await requestJson<unknown>("/api/tenant/members", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.members)) throw new ApiRequestError("The EKIP API returned an invalid tenant member list.");
  const members: TenantMember[] = payload.members.flatMap((item): TenantMember[] => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.user_id !== "string" || typeof item.email !== "string" ||
        !isTenantRole(item.role) || typeof item.is_active !== "boolean" || typeof item.created_at !== "string") return [];
    return [{ id: item.id, user_id: item.user_id, email: item.email, role: item.role, is_active: item.is_active, created_at: item.created_at }];
  });
  return { count: payload.count, members };
}

export async function updateTenantMember(
  membershipId: string,
  input: { role?: TenantRole; is_active?: boolean },
): Promise<void> {
  if (!membershipId.trim() || (!input.role && input.is_active === undefined)) throw new ApiRequestError("A member change is required.");
  await requestJson<unknown>(`/api/tenant/members/${encodeURIComponent(membershipId)}`, {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function removeTenantMember(membershipId: string): Promise<void> {
  await requestJson<unknown>(`/api/tenant/members/${encodeURIComponent(membershipId)}`, { method: "DELETE", headers: { Accept: "application/json" } });
}

export async function createTenantInvitation(input: { recipient_email: string; role: TenantRole }): Promise<TenantInvitationCreateResponse> {
  const payload = await requestJson<unknown>("/api/tenant/members/invitations", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!isRecord(payload) || typeof payload.id !== "string" || typeof payload.recipient_email !== "string" ||
      !isTenantRole(payload.role) || (payload.invitation_token !== null && typeof payload.invitation_token !== "string") || typeof payload.expires_at !== "string") {
    throw new ApiRequestError("The EKIP API returned an invalid invitation response.");
  }
  return { id: payload.id, recipient_email: payload.recipient_email, role: payload.role, invitation_token: payload.invitation_token, expires_at: payload.expires_at };
}

export async function getTenantInvitations(signal?: AbortSignal): Promise<TenantInvitationListResponse> {
  const payload = await requestJson<unknown>("/api/tenant/members/invitations", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.invitations)) throw new ApiRequestError("The EKIP API returned an invalid invitation list.");
  const invitations: TenantInvitation[] = payload.invitations.flatMap((item): TenantInvitation[] => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.recipient_email !== "string" || !isTenantRole(item.role) ||
        typeof item.invited_by_email !== "string" || typeof item.expires_at !== "string" || typeof item.created_at !== "string") return [];
    return [{ id: item.id, recipient_email: item.recipient_email, role: item.role, invited_by_email: item.invited_by_email, expires_at: item.expires_at, created_at: item.created_at }];
  });
  return { count: payload.count, invitations };
}

export async function revokeTenantInvitation(invitationId: string): Promise<void> {
  await requestJson<unknown>(`/api/tenant/members/invitations/${encodeURIComponent(invitationId)}`, { method: "DELETE", headers: { Accept: "application/json" } });
}

export async function getTenantSettings(signal?: AbortSignal): Promise<TenantSettings> {
  const payload = await requestJson<unknown>("/api/tenant/settings", { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.organisation_id !== "string" || !Array.isArray(payload.allowed_email_domains) ||
      !payload.allowed_email_domains.every((domain) => typeof domain === "string") || typeof payload.session_idle_timeout_minutes !== "number") {
    throw new ApiRequestError("The EKIP API returned invalid tenant settings.");
  }
  return payload as unknown as TenantSettings;
}

export async function updateTenantSettings(input: { allowed_email_domains: string[]; session_idle_timeout_minutes: number }): Promise<TenantSettings> {
  const payload = await requestJson<unknown>("/api/tenant/settings", {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!isRecord(payload) || typeof payload.organisation_id !== "string" || !Array.isArray(payload.allowed_email_domains) ||
      !payload.allowed_email_domains.every((domain) => typeof domain === "string") || typeof payload.session_idle_timeout_minutes !== "number") {
    throw new ApiRequestError("The EKIP API returned invalid tenant settings.");
  }
  return payload as unknown as TenantSettings;
}

export async function getTenantAuditEvents(options: { limit?: number; before?: string } = {}, signal?: AbortSignal): Promise<TenantAuditEventListResponse> {
  const params = new URLSearchParams({ limit: String(options.limit ?? 100) });
  if (options.before) params.set("before", options.before);
  const payload = await requestJson<unknown>(`/api/audit/events?${params.toString()}`, { headers: { Accept: "application/json" }, signal });
  if (!isRecord(payload) || typeof payload.count !== "number" || !Array.isArray(payload.events)) throw new ApiRequestError("The EKIP API returned an invalid tenant audit log.");
  const events: TenantAuditEvent[] = payload.events.flatMap((item): TenantAuditEvent[] => {
    if (!isRecord(item) || typeof item.id !== "string" || typeof item.event_type !== "string" || typeof item.occurred_at !== "string" ||
        (item.actor_user_id !== null && typeof item.actor_user_id !== "string") || typeof item.organisation_id !== "string" ||
        (item.target_type !== null && typeof item.target_type !== "string") || (item.target_id !== null && typeof item.target_id !== "string") || !isRecord(item.details)) return [];
    const details: Record<string, string | number | boolean | null> = {};
    for (const [key, value] of Object.entries(item.details)) if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") details[key] = value;
    return [{ id: item.id, actor_user_id: item.actor_user_id as string | null, organisation_id: item.organisation_id, event_type: item.event_type, target_type: item.target_type as string | null, target_id: item.target_id as string | null, occurred_at: item.occurred_at, details }];
  });
  return { count: payload.count, events };
}

function isTenantRole(value: unknown): value is TenantRole {
  return value === "organisation_administrator" || value === "contributor" || value === "reader";
}
