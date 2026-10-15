import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, getHealth, postQuery, readApiDetail } from "./client";

afterEach(() => vi.unstubAllGlobals());

describe("query API client", () => {
  it("turns FastAPI validation arrays into readable errors", async () => {
    const errors = [{ loc: ["body", "top_k"], msg: "Input should be less than or equal to 20", type: "less_than_equal" }];
    expect(readApiDetail({ detail: errors })).toBe("body → top_k: Input should be less than or equal to 20");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: errors }), { status: 422 })));
    try {
      await postQuery({ question: "q", top_k: 21 }, new AbortController().signal);
      throw new Error("Expected the request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      expect((error as Error).message).toContain("body → top_k");
    }
  });

  it("handles string and object error details safely", () => {
    expect(readApiDetail({ detail: "Bad question" })).toBe("Bad question");
    expect(readApiDetail({ detail: { message: "Invalid request" } })).toBe("Invalid request");
    expect(readApiDetail({ detail: { unexpected: true } })).toBeUndefined();
  });

  it("preserves a gateway status when a 504 body is HTML", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>gateway timeout</html>", { status: 504 })));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toThrow(
      "The server took too long to respond or is unavailable (HTTP 504). The query may still be running. Try again shortly.",
    );
  });

  it("preserves a gateway status when a 502 body is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 502 })));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toThrow(
      "The server took too long to respond or is unavailable (HTTP 502). The query may still be running. Try again shortly.",
    );
  });

  it("uses a rate-limit message for an unhelpful 429 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(" ", { status: 429 })));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toThrow(
      "Too many requests (HTTP 429). Wait a moment and try again.",
    );
  });

  it("keeps a clear unreadable-response error for successful invalid JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toThrow(
      "The EKIP API returned an unreadable response.",
    );
  });

  it("keeps the existing message when the network request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toThrow(
      "Cannot reach the EKIP API. Check that the backend is running.",
    );
  });

  it("rethrows AbortError unchanged", async () => {
    const abortError = new DOMException("The request was aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));
    await expect(postQuery({ question: "q", top_k: 5 }, new AbortController().signal)).rejects.toBe(abortError);
  });

  it("requests the standardized /api/query path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ answer: "ok" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await postQuery({ question: "q", top_k: 5 }, new AbortController().signal);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/query");
  });

  it("requests the standardized /api/health path without changing health parsing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", document_count: 2 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getHealth()).resolves.toMatchObject({ status: "ok", document_count: 2 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });
});
