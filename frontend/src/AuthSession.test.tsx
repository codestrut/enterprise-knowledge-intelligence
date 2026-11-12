import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import DocumentLibrary from "./DocumentLibrary";
import { setAccessToken } from "./api/client";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); setAccessToken(null); window.history.replaceState({}, "", "/"); document.title = ""; });

const PASSWORD = "correct-horse-battery-staple";
const ADMIN_PERMISSIONS = ["documents:read", "documents:upload", "documents:delete", "documents:query"];

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}
function profile(email: string, organisation: string) {
  return { email, organisation: { id: `org-${organisation}`, name: organisation }, role: "organisation_administrator", permissions: ADMIN_PERMISSIONS };
}
function tokens(token: string) {
  return { access_token: token, token_type: "bearer", expires_in: 600, refresh_token: `refresh-${token}`, organisation_id: "org", role: "organisation_administrator", permissions: ADMIN_PERMISSIONS };
}
function bearer(init?: RequestInit) { return new Headers(init?.headers).get("Authorization"); }
async function submitSignIn(email: string, password = PASSWORD) {
  fireEvent.change(await screen.findByLabelText("Work email"), { target: { value: email } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /Sign in securely/ }));
}
async function signOut() {
  fireEvent.click(document.querySelector(".account-menu summary")!);
  fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
}

describe("F2: explicit auth states and fail-closed permissions", () => {
  it("shows a neutral loading state, no app shell and no write controls while the session is unknown", async () => {
    window.history.replaceState({}, "", "/library");
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    render(<App/>);
    expect((await screen.findByRole("status")).textContent).toContain("Checking your session");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Upload a PDF" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByLabelText("Work email")).toBeNull();
  });

  it.each([
    ["a network error", () => Promise.reject(new TypeError("offline"))],
    ["a 5xx response", () => Promise.resolve(json({ detail: "Database unavailable at db-host-canary" }, 503))],
  ])("ends initial resolution signed out with fixed text after %s", async (_name, resolveMe) => {
    vi.stubGlobal("fetch", vi.fn((url: string) => url === "/api/auth/me" ? resolveMe() : Promise.resolve(json({ detail: "Unexpected" }, 404))));
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toBe("We couldn't confirm your sign-in status. Sign in to continue.");
    expect(document.body.textContent).not.toContain("db-host-canary");
  });

  it("treats unknown permissions as deny", () => {
    render(<DocumentLibrary/>);
    expect(screen.queryByRole("heading", { name: "Upload a PDF" })).toBeNull();
  });
});

describe("F1: session-scoped state is cleared between users", () => {
  it("does not show the previous user's documents or answers after another user signs in", async () => {
    window.history.replaceState({}, "", "/library");
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit = {}) => {
      const auth = bearer(init);
      if (url === "/api/auth/me") return Promise.resolve(auth === "Bearer token-a" ? json(profile("a@example.test", "Tenant A")) : auth === "Bearer token-b" ? json(profile("b@example.test", "Tenant B")) : json({ detail: "Authentication is required." }, 401));
      if (url === "/api/auth/login") return Promise.resolve(json(tokens(JSON.parse(String(init.body)).email === "a@example.test" ? "token-a" : "token-b")));
      if (url === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
      if (url === "/api/health") return Promise.resolve(json({ status: "ok", document_count: 1, chunk_count: 1 }));
      if (url === "/api/documents") return Promise.resolve(auth === "Bearer token-a"
        ? json({ count: 1, documents: [{ document_id: "a1", filename: "a.pdf", status: "indexed" }] })
        : json({ detail: "You do not have permission to perform this action." }, 403));
      if (url === "/api/query") return Promise.resolve(json({ answer: "Answer visible only to tenant A.", sources: [], citations: [], refused: false }));
      return Promise.resolve(json({ detail: "Unexpected request" }, 404));
    }));
    render(<App/>);
    await submitSignIn("a@example.test");
    expect((await screen.findAllByText("a.pdf")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("link", { name: /Workspace/ }));
    fireEvent.change(await screen.findByLabelText("Your question"), { target: { value: "What is private to tenant A?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask EKIP" }));
    expect(await screen.findByText("Answer visible only to tenant A.")).toBeTruthy();

    await signOut();
    await submitSignIn("b@example.test");
    expect((await screen.findAllByText("b@example.test")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.queryByText("Answer visible only to tenant A.")).toBeNull());
    fireEvent.click(screen.getByRole("link", { name: /Document library/ }));
    expect(await screen.findByRole("heading", { name: "Document management" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("a.pdf")).toBeNull());
    expect(document.body.textContent).not.toContain("a.pdf");
  });

  it("ignores a late response from the previous session after another user signs in", async () => {
    window.history.replaceState({}, "", "/library");
    let releaseLateDocuments: (() => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit = {}) => {
      const auth = bearer(init);
      if (url === "/api/auth/me") return Promise.resolve(auth === "Bearer token-a" ? json(profile("a@example.test", "Tenant A")) : auth === "Bearer token-b" ? json(profile("b@example.test", "Tenant B")) : json({ detail: "Authentication is required." }, 401));
      if (url === "/api/auth/login") return Promise.resolve(json(tokens(JSON.parse(String(init.body)).email === "a@example.test" ? "token-a" : "token-b")));
      if (url === "/api/auth/logout") return Promise.resolve(new Response(null, { status: 204 }));
      if (url === "/api/health") return Promise.resolve(json({ status: "ok", document_count: 1, chunk_count: 1 }));
      if (url === "/api/documents" && auth === "Bearer token-a") {
        return new Promise<Response>((resolve) => { releaseLateDocuments = () => resolve(json({ count: 1, documents: [{ document_id: "a1", filename: "a.pdf", status: "indexed" }] })); });
      }
      if (url === "/api/documents") return Promise.resolve(json({ count: 1, documents: [{ document_id: "b1", filename: "b.pdf", status: "indexed" }] }));
      return Promise.resolve(json({ detail: "Unexpected request" }, 404));
    }));
    render(<App/>);
    await submitSignIn("a@example.test");
    expect((await screen.findAllByText("a@example.test")).length).toBeGreaterThan(0);
    await waitFor(() => expect(releaseLateDocuments).toBeDefined());
    await signOut();
    await submitSignIn("b@example.test");
    expect((await screen.findAllByText("b.pdf")).length).toBeGreaterThan(0);
    releaseLateDocuments!();
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(document.body.textContent).not.toContain("a.pdf");
    expect(screen.getAllByText("b.pdf").length).toBeGreaterThan(0);
  });
});

describe("F4: fixed sign-in error text", () => {
  it.each([
    [503, { detail: "Authentication signing key is not configured." }, "Sign-in is temporarily unavailable. Try again shortly."],
    [429, { detail: "Too many sign-in attempts. Try again later." }, "Too many sign-in attempts. Wait a few minutes and try again."],
  ])("maps HTTP %s to fixed text without server details", async (status, body, expected) => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(url === "/api/auth/login" ? json(body, status) : json({ detail: "Authentication is required." }, 401))));
    render(<App/>);
    await submitSignIn("user@example.test");
    expect((await screen.findByRole("alert")).textContent).toBe(expected);
    expect(document.body.textContent).not.toContain("signing key");
  });
});

describe("Platform-only operator sign-in", () => {
  it("uses the explicit platform scope and routes to Platform Admin without tenant navigation", async () => {
    window.history.replaceState({}, "", "/");
    const calls: { url: string; init?: RequestInit }[] = [];
    const fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      if (url === "/api/auth/me" && bearer(init) === "Bearer platform-token") {
        return Promise.resolve(json({ email: "platform@example.test", organisation: null, role: "reader", permissions: [], platform_permissions: ["organisations:read"], platform_roles: ["platform_super_administrator"] }));
      }
      if (url === "/api/auth/me") return Promise.resolve(json({ detail: "Authentication is required." }, 401));
      if (url === "/api/auth/login") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        expect(body.auth_scope).toBe("platform");
        return Promise.resolve(json({ access_token: "platform-token", token_type: "bearer", expires_in: 600, refresh_token: "platform-refresh", organisation_id: null, role: "reader", permissions: [] }));
      }
      if (url === "/api/health") return Promise.resolve(json({ status: "ok", document_count: 0, chunk_count: 0 }));
      if (url === "/api/platform/overview") return Promise.resolve(json({ total_tenants: 0, active_tenants: 0, pending_tenants: 0, provisioning_tenants: 0, failed_tenants: 0, suspended_tenants: 0, total_documents: 0, total_chunks: 0 }));
      return Promise.resolve(json({ detail: "Unexpected request" }, 404));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App/>);
    fireEvent.click(await screen.findByLabelText("Sign in as a platform operator"));
    await submitSignIn("platform@example.test");
    expect(await screen.findByRole("heading", { name: "Platform administration" })).toBeTruthy();
    expect(screen.getAllByText("Super administrator").length).toBeGreaterThan(0);
    expect(screen.queryByText("Reader")).toBeNull();
    expect(document.title).toBe("Platform Administration · EKIP");
    expect(screen.getByRole("link", { name: /Platform admin/ })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Document library/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /Workspace/ })).toBeNull();
    expect(calls.some((call) => call.url === "/api/platform/overview")).toBe(true);
    expect(calls.some((call) => call.url === "/api/documents" || call.url === "/api/query")).toBe(false);
  });
});

describe("F3: multi-organisation sign-in", () => {
  function multiOrganisationFetch(loginBodies: Record<string, unknown>[], organisations: unknown[]) {
    return vi.fn((url: string, init: RequestInit = {}) => {
      if (url === "/api/auth/login") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        loginBodies.push(body);
        return Promise.resolve(body.organisation_id
          ? json(tokens("token-multi"))
          : json({ requires_organisation_selection: true, organisations }));
      }
      if (url === "/api/auth/me") return Promise.resolve(bearer(init) === "Bearer token-multi" ? json(profile("multi@example.test", "South Research")) : json({ detail: "Authentication is required." }, 401));
      if (url === "/api/health") return Promise.resolve(json({ status: "ok", document_count: 0, chunk_count: 0 }));
      if (url === "/api/documents") return Promise.resolve(json({ count: 0, documents: [] }));
      return Promise.resolve(json({ detail: "Unexpected request" }, 404));
    });
  }
  const choices = [{ id: "org-1", name: "North Research", slug: "north" }, { id: "org-2", name: "South Research", slug: "south" }];

  it("completes organisation selection without retyping the password", async () => {
    const loginBodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", multiOrganisationFetch(loginBodies, choices));
    render(<App/>);
    await submitSignIn("multi@example.test");
    const select = await screen.findByLabelText("Organisation");
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe(PASSWORD);
    expect(screen.getByRole("status").textContent).toContain("Choose an organisation to continue.");
    fireEvent.change(select, { target: { value: "org-2" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign in securely/ }));
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    expect(loginBodies).toEqual([
      { email: "multi@example.test", password: PASSWORD, auth_scope: "tenant" },
      { email: "multi@example.test", password: PASSWORD, organisation_id: "org-2", auth_scope: "tenant" },
    ]);
  });

  it("resets organisation choices when the email changes", async () => {
    vi.stubGlobal("fetch", multiOrganisationFetch([], choices));
    render(<App/>);
    await submitSignIn("multi@example.test");
    expect(await screen.findByLabelText("Organisation")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "someone-else@example.test" } });
    await waitFor(() => expect(screen.queryByLabelText("Organisation")).toBeNull());
  });

  it("shows fixed text when no organisation is available", async () => {
    vi.stubGlobal("fetch", multiOrganisationFetch([], []));
    render(<App/>);
    await submitSignIn("multi@example.test");
    expect((await screen.findByRole("alert")).textContent).toBe("No active organisation is available for this account. Contact your administrator.");
  });
});
