import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import App from "./App";
import { authenticatedTestProfile, withAuthenticatedProfile } from "./test-fixtures/auth";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); document.title = ""; });

function mockApi({ health = { status: "ok", document_count: 0, chunk_count: 0, failed_document_count: 0 }, documents = { count: 0, documents: [] } }: { health?: unknown; documents?: unknown } = {}) {
  const fetchMock = vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/health" ? health : documents), { status: 200, headers: { "Content-Type": "application/json" } })));
  // F2: answer the session check so these signed-in views render; fetchMock still sees only status calls.
  vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock));
  return fetchMock;
}

describe("shared application shell and routes", () => {
  it("prompts for managed sign-in after 401, attaches the bearer token, and hides reader write actions", async () => {
    window.history.replaceState({}, "", "/library");
    const calls: { url: string; headers?: Headers }[] = [];
    let expired = false;
    const fetchMock = vi.fn((input: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      calls.push({ url: input, headers });
      if (input === "/api/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      if (input === "/api/auth/login") return Promise.resolve(new Response(JSON.stringify({ access_token: "test-access-token", token_type: "bearer", expires_in: 600, refresh_token: "unused-in-memory-test", organisation_id: "org-1", role: "reader", permissions: ["documents:read", "documents:query"] }), { status: 200 }));
      if (input === "/api/auth/me" && headers.get("Authorization") === "Bearer test-access-token") return Promise.resolve(new Response(JSON.stringify({ email: "reader@example.test", organisation: { id: "org-1", name: "Research Group" }, role: "reader", permissions: ["documents:read", "documents:query"] }), { status: 200 }));
      if (input === "/api/documents" && headers.get("Authorization") === "Bearer test-access-token" && !expired) return Promise.resolve(new Response(JSON.stringify({ count: 1, documents: [{ document_id: "doc-1", filename: "handbook.pdf", status: "indexed" }] }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ detail: "Authentication is required." }), { status: 401 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App/>);

    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "reader@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct-horse-battery-staple" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign in securely/ }));

    expect((await screen.findAllByText("handbook.pdf")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("heading", { name: "Upload a PDF" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(calls.filter((call) => call.url === "/api/documents" && call.headers?.get("Authorization")).length).toBeGreaterThan(0);
    expired = true;
    fireEvent.click(screen.getByRole("button", { name: "Refresh library" }));
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Your session expired");
  });

  it("uses the supplied research image paths, supports password visibility, and signs out locally if revocation fails", async () => {
    window.history.replaceState({}, "", "/");
    const calls: { url: string; init: RequestInit }[] = [];
    const fetchMock = vi.fn((input: string, init: RequestInit = {}) => {
      calls.push({ url: input, init });
      if (input === "/api/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok", document_count: 0, chunk_count: 0 }), { status: 200 }));
      if (input === "/api/documents") return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      if (input === "/api/auth/login") return Promise.resolve(new Response(JSON.stringify({ access_token: "session-in-memory", token_type: "bearer", expires_in: 600, refresh_token: "synthetic-test-only", organisation_id: "org-2", role: "organisation_administrator", permissions: ["documents:read", "documents:upload", "documents:delete", "documents:query"] }), { status: 200 }));
      if (input === "/api/auth/me") return Promise.resolve(new Response(JSON.stringify({ email: "admin@example.test", organisation: { id: "org-2", name: "North Research" }, role: "organisation_administrator", permissions: ["documents:read", "documents:upload", "documents:delete", "documents:query"] }), { status: 200 }));
      if (input === "/api/auth/logout") return Promise.resolve(new Response(JSON.stringify({ detail: "temporarily unavailable" }), { status: 503 }));
      return Promise.resolve(new Response(JSON.stringify({ detail: "Unexpected request" }), { status: 404 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/documents", expect.anything()));
    act(() => window.dispatchEvent(new CustomEvent("ekip:auth-required")));
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    const image = screen.getByAltText(/Researchers studying documents/);
    expect(image.getAttribute("src")).toBe("/images/ekip-login-research-rotation.gif");
    expect(image.parentElement?.querySelector('source[media="(prefers-reduced-motion: reduce)"]')?.getAttribute("srcset")).toBe("/images/ekip-login-research-rotation-poster.jpg");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect((screen.getByLabelText("Password") as HTMLInputElement).type).toBe("text");
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "admin@example.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "safe-test-password" } });
    fireEvent.click(screen.getByRole("button", { name: /Sign in securely/ }));
    await waitFor(() => expect(fetchMock.mock.calls.map(([url]) => url)).toContain("/api/auth/me"));
    expect((await screen.findAllByText("admin@example.test")).length).toBeGreaterThan(0);
    fireEvent.click(document.querySelector(".account-menu summary")!);
    expect((await screen.findAllByText("North Research")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Admin").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    expect((await screen.findByRole("alert")).textContent).toContain("server could not confirm session revocation");
    const logoutCall = calls.find((call) => call.url === "/api/auth/logout");
    expect(logoutCall?.init.method).toBe("POST");
  });

  it("falls back from the animation to the poster and keeps the login form if both assets fail", async () => {
    window.history.replaceState({}, "", "/");
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/health" ? { status: "ok" } : { detail: "Authentication is required." }), { status: url === "/api/health" ? 200 : 401 }))));
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    const image = screen.getByAltText(/Researchers studying documents/);
    expect(image.getAttribute("src")).toBe("/images/ekip-login-research-rotation.gif");
    fireEvent.error(image);
    expect(image.getAttribute("src")).toBe("/images/ekip-login-research-rotation-poster.jpg");
    fireEvent.error(image);
    expect(screen.queryByLabelText("Research workspace")).toBeNull();
    expect(screen.getByLabelText("Work email")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Sign in securely/ })).toBeTruthy();
  });

  it("shows the compact dashboard, separate API and knowledge states, and truthful first-use steps", async () => {
    mockApi();
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    // F2: status loads after the session check resolves, so wait for it rather than racing it.
    expect((await screen.findAllByText("API connected")).length).toBeGreaterThan(0);
    expect(screen.getByText("No documents indexed")).toBeTruthy();
    expect(screen.getByText("Upload a PDF", { selector: "a" })).toBeTruthy();
    const steps = screen.getByText("First-use checklist").closest("section")!;
    expect(within(steps).getByText("Upload a PDF").closest("li")?.className).toBe("");
    expect(within(steps).getByText("Ask a question").closest("li")?.className).toBe("");
    expect(within(steps).getByText("Review the citations").closest("li")?.className).toBe("");
    expect(screen.queryByText("A clearer view of what your knowledge can do.")).toBeNull();
  });

  it("shows indexed counts without inventing a failed count when that health field is null", async () => {
    mockApi({ health: { status: "ok", document_count: 3, chunk_count: 28, failed_document_count: null }, documents: { count: 3, documents: [{ document_id: "1", filename: "a.pdf" }, { document_id: "2", filename: "b.pdf" }, { document_id: "3", filename: "c.pdf" }] } });
    render(<App/>);
    expect(await screen.findByText("3 documents indexed")).toBeTruthy();
    expect(screen.getByText("28")).toBeTruthy();
    expect(screen.queryByText("Documents needing attention")).toBeNull();
    const checklist = screen.getByText("First-use checklist").closest("section")!;
    expect(within(checklist).getByText("Upload a PDF").closest("li")?.className).toContain("is-complete");
    expect(within(checklist).getByText("Ask a question").closest("li")?.className).toBe("");
  });

  it("reuses a single health and document fetch while navigating pages", async () => {
    const fetchMock = mockApi();
    render(<App/>);
    await screen.findByRole("heading", { name: "Knowledge operations" });
    fireEvent.click(screen.getByRole("link", { name: /Document library/ }));
    expect(await screen.findByRole("heading", { name: "Document management" })).toBeTruthy();
    expect(document.title).toBe("Document Management · EKIP");
    fireEvent.click(screen.getByRole("link", { name: /Workspace/ }));
    expect(await screen.findByRole("heading", { name: "Ask your knowledge base" })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("navigation", { name: "Main navigation" }).querySelector('[aria-current="page"]')?.getAttribute("href")).toBe("/workspace");
  });

  it("deduplicates the initial status request under React StrictMode effect replay", async () => {
    const fetchMock = mockApi();
    render(<StrictMode><App/></StrictMode>);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("supports browser back/forward, title changes, and focuses the new heading", async () => {
    mockApi();
    render(<App/>);
    await screen.findByRole("heading", { name: "Knowledge operations" });
    fireEvent.click(screen.getByRole("link", { name: /Workspace/ }));
    expect(await screen.findByRole("heading", { name: "Ask your knowledge base" })).toBeTruthy();
    await act(async () => { window.history.back(); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    expect(document.title).toBe("System Overview · EKIP");
    await act(async () => { window.history.forward(); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(await screen.findByRole("heading", { name: "Ask your knowledge base" })).toBeTruthy();
  });

  it("renders a 404 route with a working home link", async () => {
    window.history.replaceState({}, "", "/unknown");
    mockApi();
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "This page isn’t here" })).toBeTruthy();
    expect(document.title).toBe("Page not found · EKIP");
    fireEvent.click(screen.getByRole("link", { name: /Go to system overview/ }));
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
  });

  it("does not show healthy or ready claims when the status endpoints fail", async () => {
    vi.stubGlobal("fetch", withAuthenticatedProfile(vi.fn().mockRejectedValue(new TypeError("offline"))));
    render(<App/>);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("API connected")).toBeNull();
    expect(screen.queryByText("No documents indexed")).toBeNull();
  });

  it("shows workspace empty guidance while keeping questions usable, and example chips only fill and focus", async () => {
    window.history.replaceState({}, "", "/workspace");
    const fetchMock = mockApi();
    render(<App/>);
    expect(await screen.findByText(/Answers depend on indexed documents/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Upload a PDF" }).getAttribute("href")).toBe("/library");
    const textarea = screen.getByLabelText("Your question") as HTMLTextAreaElement;
    fireEvent.click(screen.getByRole("button", { name: "Summarize the key risks." }));
    expect(textarea.value).toBe("Summarize the key risks.");
    expect(document.activeElement).toBe(textarea);
    expect(screen.getByRole("button", { name: "Ask EKIP" })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keeps workspace questions available when shared status requests fail", async () => {
    window.history.replaceState({}, "", "/workspace");
    vi.stubGlobal("fetch", withAuthenticatedProfile(vi.fn().mockRejectedValue(new TypeError("offline"))));
    render(<App/>);
    expect(await screen.findByRole("heading", { name: "Ask your knowledge base" })).toBeTruthy();
    expect(screen.getByLabelText("Your question")).toBeTruthy();
    expect(screen.queryByText(/Searching \d+ documents/)).toBeNull();
    expect(screen.queryByText(/Answers depend on indexed documents/)).toBeNull();
  });

  it("shows a reliable document scope and names in a disclosure when there are ten or fewer", async () => {
    window.history.replaceState({}, "", "/workspace");
    mockApi({ health: { status: "ok", document_count: 2, chunk_count: 18 }, documents: { count: 2, documents: [{ ...{ document_id: "1", filename: "handbook.pdf" } }, { document_id: "2", filename: "guide.pdf" }] } });
    render(<App/>);
    expect(await screen.findByText("Searching 2 documents")).toBeTruthy();
    fireEvent.click(screen.getByText("View documents"));
    expect(screen.getByText("handbook.pdf")).toBeTruthy();
    expect(screen.getByText("guide.pdf")).toBeTruthy();
  });

  it("renders admin role badge in AppShell for administrator profile", async () => {
    mockApi();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    const adminBadges = screen.getAllByText("Admin");
    expect(adminBadges.length).toBeGreaterThan(0);
    expect(adminBadges[0].getAttribute("data-role")).toBe("organisation_administrator");
  });

  it("renders contributor role badge in AppShell for contributor profile", async () => {
    const contributorProfile = { ...authenticatedTestProfile, role: "contributor" };
    vi.stubGlobal("fetch", withAuthenticatedProfile(vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/health" ? { status: "ok" } : { count: 0, documents: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))), contributorProfile));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    const contribBadges = screen.getAllByText("Contributor");
    expect(contribBadges.length).toBeGreaterThan(0);
    expect(contribBadges[0].getAttribute("data-role")).toBe("contributor");
  });

  it("renders reader role badge in AppShell for reader profile", async () => {
    const readerProfile = { ...authenticatedTestProfile, role: "reader" };
    vi.stubGlobal("fetch", withAuthenticatedProfile(vi.fn((url: string) => Promise.resolve(new Response(JSON.stringify(url === "/api/health" ? { status: "ok" } : { count: 0, documents: [] }), { status: 200, headers: { "Content-Type": "application/json" } }))), readerProfile));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    const readerBadges = screen.getAllByText("Reader");
    expect(readerBadges.length).toBeGreaterThan(0);
    expect(readerBadges[0].getAttribute("data-role")).toBe("reader");
  });

  it("renders the dedicated 403 Forbidden page on /403 with working return navigation", async () => {
    window.history.replaceState({}, "", "/403");
    mockApi();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Access is forbidden" })).toBeTruthy();
    expect(screen.getByText("403 · ACCESS RESTRICTED")).toBeTruthy();
    expect(document.title).toBe("Access Forbidden · EKIP");

    fireEvent.click(screen.getByRole("link", { name: "Return to system overview" }));
    expect(await screen.findByRole("heading", { name: "Knowledge operations" })).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });


  it("allows platform readers to access tenant administration and loads the tenant list", async () => {
    window.history.replaceState({}, "", "/platform");

    const profile = {
      ...authenticatedTestProfile,
      platform_permissions: ["organisations:read"],
    };
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/health") {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }
      if (input === "/api/documents") {
        return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      }
      if (input === "/api/platform/organisations") {
        return Promise.resolve(new Response(JSON.stringify({ count: 1, organisations: [{
          id: "org-platform-test",
          name: "Platform Test Organisation",
          slug: "platform-test",
          status: "active",
          is_active: true,
          initial_admin_email: "tenant-admin@example.test",
          provisioning_attempts: 1,
          provisioning_started_at: null,
          provisioning_error_code: null,
          created_at: "2026-01-01T12:00:00Z",
        }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response(JSON.stringify({ detail: "Unexpected request" }), { status: 404 }));
    });

    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Platform administration" })).toBeTruthy();
    expect(screen.getByText("View platform overview and tenants")).toBeTruthy();

    // Tenant records now load when the Tenant lifecycle tab is selected.
    fireEvent.click(screen.getByRole("tab", { name: "Tenant lifecycle" }));
    expect(window.location.pathname).toBe("/platform/organisations");

    expect(await screen.findByText("Platform Test Organisation")).toBeTruthy();
    expect(screen.getByText("platform-test")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/platform/organisations", expect.anything());
    expect(screen.queryByRole("button", { name: "Create registration" })).toBeNull();
  });

  it("denies platform access when the session lacks organisations:read", async () => {
    window.history.replaceState({}, "", "/platform");

    const profile = { ...authenticatedTestProfile, platform_permissions: [] };
    const fetchMock = vi.fn((input: string) => Promise.resolve(
      new Response(JSON.stringify(input === "/api/health" ? { status: "ok" } : { count: 0, documents: [] }), { status: 200 })
    ));

    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Access is forbidden" })).toBeTruthy();
    await waitFor(() => expect(document.title).toBe("Access Forbidden · EKIP"));
    expect(screen.queryByRole("heading", { name: "Tenant administration" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/platform/organisations", expect.anything());
    expect(screen.queryByRole("link", { name: /Platform administration/i })).toBeNull();
  });

  it("allows a platform role manager to open the access route without organisations:read", async () => {
    window.history.replaceState({}, "", "/platform/access");

    const profile = {
      ...authenticatedTestProfile,
      platform_permissions: ["platform-roles:assign"],
    };
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/health") {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }
      if (input === "/api/documents") {
        return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      }
      if (input === "/api/platform/users/roles") {
        return Promise.resolve(new Response(JSON.stringify({ count: 0, assignments: [] }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({ detail: "Unexpected request" }), { status: 404 }));
    });

    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Assign platform roles" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Access & roles" }).getAttribute("aria-selected")).toBe("true");
    expect(fetchMock).toHaveBeenCalledWith("/api/platform/users/roles", expect.anything());
  });

  it("allows a platform auditor to open the audit route without organisations:read", async () => {
    window.history.replaceState({}, "", "/platform/audit");

    const profile = {
      ...authenticatedTestProfile,
      platform_permissions: ["platform-audit:read"],
    };
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/health") {
        return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      }
      if (input === "/api/documents") {
        return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      }
      if (input.startsWith("/api/platform/audit/events")) {
        return Promise.resolve(new Response(JSON.stringify({ count: 0, events: [] }), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({ detail: "Unexpected request" }), { status: 404 }));
    });

    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Platform audit events" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Platform audit" }).getAttribute("aria-selected")).toBe("true");
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith("/api/platform/audit/events"))).toBe(true);
  });

  it("denies direct access to a platform section when its specific permission is missing", async () => {
    window.history.replaceState({}, "", "/platform/access");

    const profile = {
      ...authenticatedTestProfile,
      platform_permissions: ["organisations:read"],
    };
    const fetchMock = vi.fn((input: string) => Promise.resolve(
      new Response(JSON.stringify(input === "/api/health" ? { status: "ok" } : { count: 0, documents: [] }), { status: 200 })
    ));

    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Access is forbidden" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/platform/users/roles", expect.anything());
  });

  it("routes tenant readers to the organisation overview and exposes only granted admin sections", async () => {
    window.history.replaceState({}, "", "/tenant/settings");
    const profile = {
      ...authenticatedTestProfile,
      permissions: ["documents:read", "documents:query", "tenant:read"],
    };
    const fetchMock = vi.fn((input: string) => {
      if (input === "/api/health") return Promise.resolve(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
      if (input === "/api/documents") return Promise.resolve(new Response(JSON.stringify({ count: 0, documents: [] }), { status: 200 }));
      if (input === "/api/tenant/overview") return Promise.resolve(new Response(JSON.stringify({
        organisation_id: "org-test", organisation_name: "Test Organisation", document_count: 7,
        chunk_count: 64, failed_document_count: 0, member_count: 3,
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ detail: "Unexpected request" }), { status: 404 }));
    });
    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Organisation administration" })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Test Organisation" })).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Organisation" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByRole("button", { name: "Members & invitations" })).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith("/api/tenant/overview", expect.anything());
  });

  it("denies tenant administration when the session lacks tenant:read", async () => {
    window.history.replaceState({}, "", "/tenant/settings");
    const profile = { ...authenticatedTestProfile, permissions: ["documents:read"] };
    const fetchMock = vi.fn((input: string) => Promise.resolve(new Response(
      JSON.stringify(input === "/api/health" ? { status: "ok" } : { count: 0, documents: [] }), { status: 200 },
    )));
    vi.stubGlobal("fetch", withAuthenticatedProfile(fetchMock, profile));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Access is forbidden" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Organisation administration" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/tenant/overview", expect.anything());
    expect(screen.queryByRole("link", { name: "Organisation" })).toBeNull();
  });

  it("keeps 401, 403, and 404 views distinct", async () => {
    window.history.replaceState({}, "", "/nonexistent-page");
    mockApi();
    const { unmount } = render(<App />);
    expect(await screen.findByRole("heading", { name: "This page isn’t here" })).toBeTruthy();
    expect(screen.getByText("404 · PAGE NOT FOUND")).toBeTruthy();
    expect(screen.queryByText("403 · ACCESS RESTRICTED")).toBeNull();
    unmount();

    window.history.replaceState({}, "", "/403");
    mockApi();
    const { unmount: unmount403 } = render(<App />);
    expect(await screen.findByRole("heading", { name: "Access is forbidden" })).toBeTruthy();
    expect(screen.queryByText("404 · PAGE NOT FOUND")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Turn information into clarity." })).toBeNull();
    unmount403();

    window.history.replaceState({}, "", "/workspace");
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: "Authentication is required." }), { status: 401 }))));
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Turn information into clarity." })).toBeTruthy();
    expect(screen.queryByText("403 · ACCESS RESTRICTED")).toBeNull();
    expect(screen.queryByText("404 · PAGE NOT FOUND")).toBeNull();
  });
});
