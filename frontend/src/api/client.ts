import type { HealthResponse, QueryCitation, QueryRequest, QueryResponse, QuerySourceMapEntry } from "./types";

export class ApiRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export async function postQuery(
  request: QueryRequest,
  signal: AbortSignal,
): Promise<QueryResponse> {
  let response: Response;
  try {
    response = await fetch("/query", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new TypeError("Cannot reach the EKIP API. Check that the backend is running.");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiRequestError("The EKIP API returned an unreadable response.");
  }
  if (!response.ok) {
    throw new ApiRequestError(`${readApiDetail(payload) || `The EKIP API returned HTTP ${response.status}.`}`);
  }
  if (!isQueryResponse(payload)) {
    throw new ApiRequestError("The EKIP API returned an unexpected query response.");
  }
  return normalizeQueryResponse(payload);
}

export function readApiDetail(payload: unknown): string | undefined {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) return;
  const detail = (payload as Record<string, unknown>).detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const objectDetail = detail as Record<string, unknown>;
    for (const key of ["message", "msg", "error", "detail"]) {
      if (typeof objectDetail[key] === "string") return objectDetail[key] as string;
    }
    return;
  }
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (!item || typeof item !== "object") return "";
      const entry = item as Record<string, unknown>;
      const loc = Array.isArray(entry.loc) ? entry.loc.filter((part) => typeof part === "string" || typeof part === "number").join(" → ") : "";
      const msg = typeof entry.msg === "string" ? entry.msg : "Invalid value";
      return loc ? `${loc}: ${msg}` : msg;
    }).filter(Boolean);
    return messages.length ? messages.join(". ") : undefined;
  }
}

function isQueryResponse(value: unknown): value is QueryResponse {
  return typeof value === "object" && value !== null && !Array.isArray(value) &&
    typeof (value as Record<string, unknown>).answer === "string";
}

function normalizeQueryResponse(value: QueryResponse): QueryResponse {
  const entries = (input: unknown): Record<string, unknown>[] =>
    Array.isArray(input) ? input.filter(isRecord) : [];
  const sources = entries(value.sources).map((source) => ({
    text: typeof source.text === "string" ? source.text : undefined,
    score: typeof source.score === "number" ? source.score : null,
    metadata: isRecord(source.metadata) ? source.metadata : {},
  }));
  const citations: QueryCitation[] = entries(value.citations).flatMap((citation) => {
    const page = citation.page;
    const chunkId = citation.chunk_id;
    if (
      typeof citation.source_number !== "number" || typeof citation.source !== "string" ||
      (typeof page !== "string" && typeof page !== "number") ||
      (typeof chunkId !== "string" && typeof chunkId !== "number")
    ) return [];
    return [{ source_number: citation.source_number, source: citation.source, page, chunk_id: chunkId }];
  });
  const grounding = entries(value.grounding).map((claim) => ({
    ...claim,
    claim: typeof claim.claim === "string" ? claim.claim : undefined,
    status: typeof claim.status === "string" ? claim.status : undefined,
    reason: typeof claim.reason === "string" ? claim.reason : undefined,
    supporting_passage: typeof claim.supporting_passage === "string" ? claim.supporting_passage : undefined,
  }));
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
  const sourceMap: Record<string, QuerySourceMapEntry> = {};
  if (isRecord(value.source_map)) {
    for (const [number, rawEntry] of Object.entries(value.source_map)) {
      if (!isRecord(rawEntry)) continue;
      const { source, page, chunk_id: chunkId } = rawEntry;
      if (
        typeof source === "string" &&
        (typeof page === "string" || typeof page === "number") &&
        (typeof chunkId === "string" || typeof chunkId === "number")
      ) sourceMap[number] = { source, page, chunk_id: chunkId };
    }
  }
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function getHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  let response: Response;

  try {
    response = await fetch("/health", {
      headers: { Accept: "application/json" },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new TypeError(
      "Cannot reach the EKIP API. Check that the backend is running.",
    );
  }

  if (!response.ok) {
    throw new ApiRequestError(
      `The EKIP API returned HTTP ${response.status}.`,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiRequestError("The EKIP API returned invalid JSON.");
  }

  if (!isHealthResponse(payload)) {
    throw new ApiRequestError("The EKIP API returned an invalid health response.");
  }

  return payload;
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }

  const health = value as Record<string, unknown>;
  return (
    (health.status === undefined || health.status === null || typeof health.status === "string") &&
    isNullableNumber(health.document_count) &&
    isNullableNumber(health.chunk_count) &&
    (health.manifest_exists === undefined ||
      health.manifest_exists === null ||
      typeof health.manifest_exists === "boolean") &&
    isNullableNumber(health.failed_document_count)
  );
}

function isNullableNumber(value: unknown): boolean {
  return value === undefined || value === null || typeof value === "number";
}
