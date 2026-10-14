import type { HealthResponse } from "./types";

export class ApiRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiRequestError";
  }
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
