import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, deleteDocument, getCurrentUser, getDocuments, getHealth, login, logout, postQuery, readApiDetail, setAccessToken, uploadDocument } from "./client";
import emptyDocuments from "../test-fixtures/documents-empty.json";

afterEach(() => { setAccessToken(null); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("authentication API client", () => {
  it("keeps access and refresh credentials out of the login return value and browser storage", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ access_token: "access-secret-test", token_type: "bearer", expires_in: 600, refresh_token: "refresh-secret-test", organisation_id: "org-1", role: "reader", permissions: ["documents:read"] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(login("reader@example.test", "test-password")).resolves.toBeUndefined();
    expect(JSON.stringify(fetchMock.mock.results)).not.toContain("access-secret-test");
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("refreshes a safe request once and retries it with the rotated access token", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/api/auth/login") return Promise.resolve(new Response(JSON.stringify({ access_token: "old-access", refresh_token: "refresh-secret-test", organisation_id: "org-1", role: "reader", permissions: [] }), { status: 200 }));
      if (url === "/api/documents" && new Headers(init?.headers).get("Authorization") === "Bearer old-access") return Promise.resolve(new Response(JSON.stringify({ detail: "expired" }), { status: 401 }));
      if (url === "/api/auth/refresh") return Promise.resolve(new Response(JSON.stringify({ access_token: "new-access", refresh_token: "rotated-refresh-test" }), { status: 200 }));
      if (url === "/api/documents" && new Headers(init?.headers).get("Authorization") === "Bearer new-access") return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      return Promise.resolve(new Response("unexpected", { status: 500 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    await login("reader@example.test", "test-password");
    await expect(getDocuments()).resolves.toEqual({ count: 0, documents: [] });
    const refreshCall = calls.find((call) => call.url === "/api/auth/refresh");
    expect(refreshCall).toBeDefined();
    expect(new Headers(refreshCall?.init?.headers).has("Authorization")).toBe(false);
    const refreshBody = JSON.parse(String(refreshCall?.init?.body));
    expect(refreshBody.refresh_token).toBe("refresh-secret-test");
    expect(refreshBody.rotation_key).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(calls.filter((call) => call.url === "/api/documents")).toHaveLength(2);
    expect(new Headers(calls.at(-1)?.init?.headers).get("Authorization")).toBe("Bearer new-access");
  });

  it("shares one in-flight refresh across concurrent safe requests", async () => {
    let resolveRefresh!: (response: Response) => void;
    const refreshResponse = new Promise<Response>((resolve) => { resolveRefresh = resolve; });
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/api/auth/login") return Promise.resolve(new Response(JSON.stringify({ access_token: "old-access", refresh_token: "refresh-secret-test", organisation_id: "org-1", role: "reader", permissions: [] }), { status: 200 }));
      if (url === "/api/auth/refresh") return refreshResponse;
      if (url === "/api/documents" && new Headers(init?.headers).get("Authorization") === "Bearer old-access") return Promise.resolve(new Response("{}", { status: 401 }));
      if (url === "/api/documents") return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      return Promise.resolve(new Response("unexpected", { status: 500 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    await login("reader@example.test", "test-password");
    const first = getDocuments();
    const second = getDocuments();
    await vi.waitFor(() => expect(calls.filter((call) => call.url === "/api/auth/refresh")).toHaveLength(1));
    resolveRefresh(new Response(JSON.stringify({ access_token: "new-access", refresh_token: "rotated-refresh-test" }), { status: 200 }));
    await expect(Promise.all([first, second])).resolves.toEqual([{ count: 0, documents: [] }, { count: 0, documents: [] }]);
    expect(calls.filter((call) => call.url === "/api/auth/refresh")).toHaveLength(1);
    expect(calls.filter((call) => call.url === "/api/documents")).toHaveLength(4);
  });

  it("does not replay an upload after 401 and clears an invalid refresh session", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/api/auth/login") return Promise.resolve(new Response(JSON.stringify({ access_token: "old-access", refresh_token: "refresh-secret-test", organisation_id: "org-1", role: "reader", permissions: [] }), { status: 200 }));
      if (url === "/api/documents" && init?.method === "POST") return Promise.resolve(new Response("{}", { status: 401 }));
      if (url === "/api/auth/refresh") return Promise.resolve(new Response("{}", { status: 401 }));
      if (url === "/api/auth/me") return Promise.resolve(new Response("{}", { status: 401 }));
      return Promise.resolve(new Response("unexpected", { status: 500 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    await login("reader@example.test", "test-password");
    await expect(uploadDocument(new File(["%PDF-"], "safe.pdf"), new AbortController().signal)).rejects.toMatchObject({ status: 401 });
    expect(calls.filter((call) => call.url === "/api/documents" && call.init?.method === "POST")).toHaveLength(1);
    expect(calls.filter((call) => call.url === "/api/auth/refresh")).toHaveLength(1);
    expect(new Headers(calls.find((call) => call.url === "/api/auth/refresh")?.init?.headers).has("Authorization")).toBe(false);
    await expect(getCurrentUser()).rejects.toMatchObject({ status: 401 });
    expect(new Headers(calls.find((call) => call.url === "/api/auth/me")?.init?.headers).has("Authorization")).toBe(false);
    expect(calls.filter((call) => call.url === "/api/auth/refresh")).toHaveLength(1);
  });

  it("loads a typed current-user profile from the protected route", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ email: "reader@example.test", organisation: { id: "org-1", name: "Research Group" }, role: "reader", permissions: ["documents:read"] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("memory-only-access-token");
    await expect(getCurrentUser()).resolves.toEqual({ email: "reader@example.test", organisation: { id: "org-1", name: "Research Group" }, role: "reader", permissions: ["documents:read"] });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/me");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer memory-only-access-token");
  });

  it("accepts the existing empty 204 logout response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("memory-only-access-token");
    await expect(logout()).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/logout");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer memory-only-access-token");
  });
});

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

describe("shared document API client", () => {
  it("parses the captured real empty document-list contract", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(emptyDocuments), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getDocuments()).resolves.toEqual(emptyDocuments);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/documents");
  });

  it("posts PDF multipart data without setting Content-Type and parses upload success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: "ok", document: { document_id: "d1", filename: "safe.pdf", page_count: 2, chunk_count: 3, status: "indexed" } }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF-1.7"], "safe.pdf", { type: "application/pdf" });
    const result = await uploadDocument(file, new AbortController().signal);
    expect(result.document.document_id).toBe("d1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/documents");
    expect(fetchMock.mock.calls[0][1].body).toBeInstanceOf(FormData);
    expect((fetchMock.mock.calls[0][1].headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("preserves the object-valued duplicate detail and existing document", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: "Identical PDF content is already indexed.", existing_document: { document_id: "old", filename: "previous.pdf" } } }), { status: 409 })));
    try { await uploadDocument(new File(["%PDF-"], "new.pdf"), new AbortController().signal); throw new Error("expected rejection"); }
    catch (error) {
      expect(error).toBeInstanceOf(ApiRequestError);
      expect((error as ApiRequestError).status).toBe(409);
      expect((error as ApiRequestError).detail).toMatchObject({ existing_document: { document_id: "old" } });
      expect((error as Error).message).toMatch(/already indexed/);
    }
  });

  it("handles 400, 413, 422, HTML 504 and network errors consistently", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Only PDF files are supported." }), { status: 400 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "PDF exceeds the 25 MB upload limit." }), { status: 413 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: [{ loc: ["body", "file"], msg: "Field required" }] }), { status: 422 }))
      .mockResolvedValueOnce(new Response("<html>gateway</html>", { status: 504 }))
      .mockRejectedValueOnce(new TypeError("offline"));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["%PDF-"], "sample.pdf");
    await expect(uploadDocument(file, new AbortController().signal)).rejects.toThrow(/Only PDF/);
    await expect(uploadDocument(file, new AbortController().signal)).rejects.toThrow(/25 MB/);
    await expect(uploadDocument(file, new AbortController().signal)).rejects.toThrow(/body → file: Field required/);
    await expect(uploadDocument(file, new AbortController().signal)).rejects.toThrow(/HTTP 504/);
    await expect(uploadDocument(file, new AbortController().signal)).rejects.toThrow(/Cannot reach the EKIP API/);
  });

  it("preserves delete cleanup fields and HTTP 404 status", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ document_id: "x", file_deleted: false, cleanup_required: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Document not found: x" }), { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteDocument("x")).resolves.toMatchObject({ cleanup_required: true, file_deleted: false });
    await expect(deleteDocument("x")).rejects.toMatchObject({ status: 404 });
  });

  it("keeps an explicit abort distinguishable from other failures", async () => {
    const controller = new AbortController();
    const abortError = new DOMException("The request was aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));
    await expect(uploadDocument(new File(["%PDF-"], "safe.pdf"), controller.signal)).rejects.toBe(abortError);
  });

  it("applies the five-minute upload timeout without implying server cancellation", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const pending = uploadDocument(new File(["%PDF-"], "safe.pdf"), new AbortController().signal);
    const timeoutAssertion = expect(pending).rejects.toThrow(/upload request timed out.*server may still be indexing/i);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    await timeoutAssertion;
  });

  it("removes absolute server paths from API error text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Could not parse /srv/ekip/private/document.pdf" }), { status: 400 })));
    await expect(getDocuments()).rejects.toThrow("Could not parse document.pdf");
  });
});
