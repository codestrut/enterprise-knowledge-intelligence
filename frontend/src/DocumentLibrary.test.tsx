import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import emptyList from "./test-fixtures/documents-empty.json";
import { authenticatedTestProfile, withAuthenticatedProfile } from "./test-fixtures/auth";

// F2: the app renders only for a resolved session, so each fetch mock also answers GET /api/auth/me.
function stubFetch(implementation: Parameters<typeof withAuthenticatedProfile>[0], profile?: unknown) { vi.stubGlobal("fetch", withAuthenticatedProfile(implementation, profile)); }

const record = { document_id: "doc-1", filename: "handbook.pdf", page_count: 8, chunk_count: 22, status: "indexed" };

beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function(this: HTMLDialogElement) { this.removeAttribute("open"); this.dispatchEvent(new Event("close")); } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });

function response(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } }); }
function routeToLibrary() { window.history.replaceState({}, "", "/library"); }
function pdfFile(name = "policy.pdf", content = "%PDF-1.7\ncontent") { return new File([content], name, { type: "application/pdf" }); }

describe("document management", () => {
  it("loads the real empty-list fixture through the API parser and shows an actionable empty state", async () => {
    routeToLibrary();
    const fetchMock = vi.fn((url: string) => Promise.resolve(response(url === "/api/health" ? { status: "ok", document_count: 0, chunk_count: 0, failed_document_count: 0 } : emptyList)));
    stubFetch(fetchMock);
    render(<App/>);
    expect(await screen.findByText("Upload a PDF to start asking questions about it.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows the shared loading state and retries a failed document-list request", async () => {
    routeToLibrary();
    let fail = true;
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 0, chunk_count: 0 }));
      return Promise.resolve(fail ? response({ detail: "temporarily unavailable" }, 503) : response(emptyList));
    });
    stubFetch(fetchMock);
    render(<App/>);
    expect(await screen.findByRole("alert")).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Upload a PDF to start asking questions about it.")).toBeTruthy();
  });

  it("shows a loading skeleton while shared requests are pending", async () => {
    routeToLibrary();
    stubFetch(vi.fn(() => new Promise<Response>(() => undefined)));
    render(<App/>);
    // F2: the skeleton appears once the session check resolves; the document requests stay pending.
    await waitFor(() => expect(screen.getAllByRole("status").some((node) => node.textContent?.includes("Loading documents"))).toBe(true));
  });

  it("shows populated records, optional page/chunk fields, truncates names, and never renders paths", async () => {
    routeToLibrary();
    stubFetch(vi.fn((url: string) => Promise.resolve(response(url === "/api/health" ? { status: "ok", document_count: 1, chunk_count: 3, failed_document_count: null } : { count: 1, documents: [{ ...record, filename: "/srv/private/" + "very-long-".repeat(12) + "handbook.pdf", source: "/srv/private/file.pdf", stored_filename: "local-secret.pdf" }] }))));
    render(<App/>);
    expect((await screen.findAllByText(/handbook\.pdf/)).length).toBeGreaterThan(0);
    expect(screen.getByText("8")).toBeTruthy();
    expect(screen.getByText("22")).toBeTruthy();
    expect(document.body.textContent).not.toContain("/srv/private");
    expect(document.body.textContent).not.toContain("local-secret.pdf");
    expect(screen.getByRole("table").querySelector("caption")?.textContent).toMatch(/Indexed documents/);
  });

  it("validates extension, actual PDF signature and the real 25 MiB size limit before sending", async () => {
    routeToLibrary();
    const fetchMock = vi.fn((url: string) => Promise.resolve(response(url === "/api/health" ? { status: "ok", document_count: 0, chunk_count: 0 } : emptyList)));
    stubFetch(fetchMock);
    render(<App/>);
    await screen.findByText("Upload a PDF to start asking questions about it.");
    const input = screen.getByLabelText(/Choose PDF file/);
    fireEvent.change(input, { target: { files: [new File(["not a pdf"], "bad.pdf", { type: "application/pdf" })] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByText(/does not have a valid PDF signature/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(25 * 1024 * 1024 + 1)], "large.pdf", { type: "application/pdf" })] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByText(/exceeds the backend’s 25 MB upload limit/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fireEvent.change(input, { target: { files: [pdfFile("notes.txt")] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByText(/Choose a PDF file/)).toBeTruthy();
  });

  it("uploads with FormData, reports backend-confirmed pages/chunks, then refreshes shared state", async () => {
    routeToLibrary();
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 0, chunk_count: 0, failed_document_count: 0 }));
      if (url === "/api/documents" && init?.method === "POST") return Promise.resolve(response({ message: "Document indexed and registered successfully.", document: record }, 201));
      return Promise.resolve(response({ count: 0, documents: [] }));
    });
    stubFetch(fetchMock);
    render(<App/>);
    await screen.findByText("Upload a PDF to start asking questions about it.");
    fireEvent.change(screen.getByLabelText(/Choose PDF file/), { target: { files: [pdfFile()] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByText(/Indexing confirmed/)).toBeTruthy();
    expect(screen.getByText(/8 pages · 22 chunks/)).toBeTruthy();
    const upload = calls.find((call) => call.init?.method === "POST")!;
    expect(upload.url).toBe("/api/documents");
    expect(upload.init?.body).toBeInstanceOf(FormData);
    expect((upload.init?.headers as Record<string, string>)?.["Content-Type"]).toBeUndefined();
    expect(calls.filter((call) => call.url === "/api/health")).toHaveLength(2);
    expect(calls.filter((call) => call.url === "/api/documents" && call.init?.method !== "POST")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Ask about this document/ }).getAttribute("href")).toBe("/workspace");
  });

  it("prevents a second upload request while the first upload is waiting", async () => {
    routeToLibrary();
    const calls: RequestInit[] = [];
    stubFetch(vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 0, chunk_count: 0 }));
      if (init?.method === "POST") { calls.push(init); return new Promise<Response>(() => undefined); }
      return Promise.resolve(response(emptyList));
    }));
    render(<App/>);
    await screen.findByText("Upload a PDF to start asking questions about it.");
    fireEvent.change(screen.getByLabelText(/Choose PDF file/), { target: { files: [pdfFile()] } });
    const form = screen.getByLabelText(/Choose PDF file/).closest("form")!;
    fireEvent.submit(form); fireEvent.submit(form);
    await screen.findByRole("button", { name: "Stop waiting" });
    expect(calls).toHaveLength(1);
  });

  it.each([
    [409, { detail: { message: "Identical PDF content is already indexed.", existing_document: record } }, /already indexed/],
    [400, { detail: "Only PDF files are supported." }, /Only PDF files are supported/],
    [413, { detail: "PDF exceeds the 25 MB upload limit." }, /25 MB upload limit/],
    [422, { detail: [{ loc: ["body", "file"], msg: "Field required" }] }, /body → file: Field required/],
    [504, "<html>gateway</html>", /server took too long/],
  ])("shows actionable upload HTTP %i feedback", async (status, payload, expected) => {
    routeToLibrary();
    const fetchMock = vi.fn((url: string, init?: RequestInit) => Promise.resolve(url === "/api/health" ? response({ status: "ok", document_count: 0, chunk_count: 0 }) : url === "/api/documents" && init?.method === "POST" ? new Response(typeof payload === "string" ? payload : JSON.stringify(payload), { status, headers: typeof payload === "string" ? { "Content-Type": "text/html" } : { "Content-Type": "application/json" } }) : response(emptyList)));
    stubFetch(fetchMock);
    render(<App/>);
    await screen.findByText("Upload a PDF to start asking questions about it.");
    fireEvent.change(screen.getByLabelText(/Choose PDF file/), { target: { files: [pdfFile()] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toMatch(expected);
  });

  it("focuses the matching listed row after an object-valued duplicate response", async () => {
    routeToLibrary();
    stubFetch(vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 1, chunk_count: 22 }));
      if (url === "/api/documents" && init?.method === "POST") return Promise.resolve(response({ detail: { message: "Identical PDF content is already indexed.", existing_document: record } }, 409));
      return Promise.resolve(response({ count: 1, documents: [record] }));
    }));
    render(<App/>);
    await screen.findAllByText("handbook.pdf");
    fireEvent.change(screen.getByLabelText(/Choose PDF file/), { target: { files: [pdfFile("new-name.pdf")] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(document.activeElement?.classList.contains("document-card")).toBe(true);
  });

  it("stops waiting without claiming to cancel server indexing, then offers refresh", async () => {
    routeToLibrary();
    stubFetch(vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 0, chunk_count: 0 }));
      if (init?.method === "POST") return new Promise((_resolve, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
      return Promise.resolve(response(emptyList));
    }));
    render(<App/>);
    await screen.findByText("Upload a PDF to start asking questions about it.");
    fireEvent.change(screen.getByLabelText(/Choose PDF file/), { target: { files: [pdfFile()] } });
    fireEvent.click(screen.getByRole("button", { name: /Upload and index/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Stop waiting" }));
    expect(await screen.findByText(/server may still finish indexing/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Refresh library" }).length).toBeGreaterThan(0);
  });

  it("requires deletion confirmation, refreshes after success, and reports cleanup_required", async () => {
    routeToLibrary();
    let listed = true;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: listed ? 1 : 0, chunk_count: listed ? 22 : 0 }));
      if (url.startsWith("/api/documents/") && init?.method === "DELETE") { listed = false; return Promise.resolve(response({ document_id: "doc-1", filename: "handbook.pdf", chunks_removed: 22, file_deleted: false, cleanup_required: true })); }
      return Promise.resolve(response(listed ? { count: 1, documents: [record] } : emptyList));
    });
    stubFetch(fetchMock);
    render(<App/>);
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/handbook\.pdf/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete document" }));
    expect(await screen.findByText(/stored file still needs cleanup/)).toBeTruthy();
    expect(await screen.findByText("No documents indexed")).toBeTruthy();
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "DELETE")).toHaveLength(1);
  });

  it("handles 404 deletion by refreshing and keeps a record after other deletion failures", async () => {
    routeToLibrary();
    let deleted = false;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: deleted ? 0 : 1, chunk_count: deleted ? 0 : 2 }));
      if (url.startsWith("/api/documents/") && init?.method === "DELETE") { deleted = true; return Promise.resolve(response({ detail: "Document not found: doc-1" }, 404)); }
      return Promise.resolve(response(deleted ? emptyList : { count: 1, documents: [record] }));
    });
    stubFetch(fetchMock);
    render(<App/>);
    await screen.findAllByText("handbook.pdf");
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete document" }));
    expect(await screen.findByText(/no longer exists/)).toBeTruthy();
    expect(await screen.findByText("No documents indexed")).toBeTruthy();
  });

  it("leaves the document in the list after a non-404 deletion failure and supports cancel", async () => {
    routeToLibrary();
    stubFetch(vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 1, chunk_count: 2 }));
      if (init?.method === "DELETE") return Promise.resolve(response({ detail: "Could not persist document deletion." }, 500));
      return Promise.resolve(response({ count: 1, documents: [record] }));
    }));
    render(<App/>);
    await screen.findAllByText("handbook.pdf");
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete document" }));
    expect(await screen.findByText("Could not persist document deletion.")).toBeTruthy();
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
  });

  it("disables repeated deletion while a request is pending", async () => {
    routeToLibrary();
    let resolveDelete: ((response: Response) => void) | undefined;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(response({ status: "ok", document_count: 1, chunk_count: 2 }));
      if (init?.method === "DELETE") return new Promise<Response>((resolve) => { resolveDelete = resolve; });
      return Promise.resolve(response({ count: 1, documents: [record] }));
    });
    stubFetch(fetchMock);
    render(<App/>);
    await screen.findAllByText("handbook.pdf");
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    const confirm = within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete document" });
    fireEvent.click(confirm);
    expect(confirm.hasAttribute("disabled")).toBe(true);
    expect(fetchMock.mock.calls.filter((call) => call[1]?.method === "DELETE")).toHaveLength(1);
    await act(async () => resolveDelete?.(response({ document_id: "doc-1", file_deleted: true, cleanup_required: false })));
  });

  it("hides upload controls and delete action buttons from reader users", async () => {
    routeToLibrary();
    const readerProfile = {
      ...authenticatedTestProfile,
      role: "reader",
      permissions: ["documents:read", "documents:query"],
    };
    stubFetch(
      vi.fn((url: string) =>
        Promise.resolve(
          response(
            url === "/api/health"
              ? { status: "ok", document_count: 1, chunk_count: 22 }
              : { count: 1, documents: [record] }
          )
        )
      ),
      readerProfile
    );
    render(<App />);
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    // Reader must not see upload form, input, or submit button
    expect(screen.queryByLabelText(/Choose PDF file/)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Upload a PDF" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Upload and index/ })).toBeNull();
    // Reader must not see delete action buttons in table or cards
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("shows upload and delete controls for contributor and admin users", async () => {
    routeToLibrary();
    const contributorProfile = {
      ...authenticatedTestProfile,
      role: "contributor",
      permissions: ["documents:read", "documents:query", "documents:upload", "documents:delete"],
    };
    stubFetch(
      vi.fn((url: string) =>
        Promise.resolve(
          response(
            url === "/api/health"
              ? { status: "ok", document_count: 1, chunk_count: 22 }
              : { count: 1, documents: [record] }
          )
        )
      ),
      contributorProfile
    );
    render(<App />);
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Choose PDF file/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Upload a PDF" })).toBeTruthy();
    expect(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ })).toBeTruthy();
  });

  it("displays intended document name safely and provides accessible labelling", async () => {
    routeToLibrary();
    const untrustedDoc = {
      ...record,
      filename: "reports/quarterly/<script>alert(1)</script>finance.pdf",
    };
    stubFetch(
      vi.fn((url: string) =>
        Promise.resolve(
          response(
            url === "/api/health"
              ? { status: "ok", document_count: 1, chunk_count: 22 }
              : { count: 1, documents: [untrustedDoc] }
          )
        )
      )
    );
    render(<App />);
    expect((await screen.findAllByText(/finance\.pdf/)).length).toBeGreaterThan(0);
    fireEvent.click(within(screen.getByRole("table")).getByRole("button", { name: /Delete/ }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeTruthy();
    expect(within(dialog).getByText(/finance\.pdf/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("reports/quarterly");
    expect(dialog.getAttribute("aria-labelledby")).toBe("delete-dialog-title");
    expect(dialog.getAttribute("aria-describedby")).toBe("delete-dialog-description");
  });

  it("moves focus into dialog when opened and restores focus to initiating control when dismissed", async () => {
    routeToLibrary();
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(
        response(
          url === "/api/health"
            ? { status: "ok", document_count: 1, chunk_count: 22 }
            : { count: 1, documents: [record] }
        )
      );
    });
    stubFetch(fetchMock);
    render(<App />);
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    const deleteBtn = within(screen.getByRole("table")).getByRole("button", { name: /Delete/ });
    deleteBtn.focus();
    expect(document.activeElement).toBe(deleteBtn);

    // Open dialog
    fireEvent.click(deleteBtn);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeTruthy();
    // Focus moves into dialog to Cancel button
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBe(document.activeElement);

    // Dismiss with Cancel button
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((call) => call.init?.method === "DELETE")).toHaveLength(0);
    // Focus restores to initiating button
    expect(document.activeElement).toBe(deleteBtn);
  });

  it("dismisses dialog on Escape key without calling deletion API and restores focus", async () => {
    routeToLibrary();
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(
        response(
          url === "/api/health"
            ? { status: "ok", document_count: 1, chunk_count: 22 }
            : { count: 1, documents: [record] }
        )
      );
    });
    stubFetch(fetchMock);
    render(<App />);
    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    const deleteBtn = within(screen.getByRole("table")).getByRole("button", { name: /Delete/ });
    deleteBtn.focus();
    fireEvent.click(deleteBtn);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeTruthy();

    // Dismiss with Escape key
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.filter((call) => call.init?.method === "DELETE")).toHaveLength(0);
    expect(document.activeElement).toBe(deleteBtn);
  });
});
