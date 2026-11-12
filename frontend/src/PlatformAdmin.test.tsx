import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockUseAuth } = vi.hoisted(() => ({ mockUseAuth: vi.fn() }));
vi.mock("./AuthContext", () => ({ useAuth: mockUseAuth }));

import PlatformAdmin from "./PlatformAdmin";
import { setAccessToken } from "./api/client";

const overview = {
  total_tenants: 12, active_tenants: 8, pending_tenants: 1, provisioning_tenants: 1,
  failed_tenants: 1, suspended_tenants: 1, total_documents: 240, total_chunks: 3800,
};
const baseOrganisations = [
  { id: "org-active", name: "North Research", slug: "north-research", is_active: true, status: "active", initial_admin_email: "admin@north.test", provisioning_attempts: 1, provisioning_started_at: null, provisioning_error_code: null, created_at: "2026-01-01T00:00:00Z" },
  { id: "org-suspended", name: "South Research", slug: "south-research", is_active: false, status: "suspended", initial_admin_email: "admin@south.test", provisioning_attempts: 1, provisioning_started_at: null, provisioning_error_code: null, created_at: "2026-01-02T00:00:00Z" },
];
const baseAssignments = [
  { id: "assignment-1", user_id: "user-1", email: "owner@example.test", role: "platform_tenant_creator", assigned_at: "2026-01-01T00:00:00Z" },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockPlatformSession(permissions: string[]) {
  mockUseAuth.mockReturnValue({ profile: { email: "platform@example.test", organisation: null, permissions: [], platform_permissions: permissions } });
}

function setupFetch(options: { searchStatus?: number } = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const organisations = baseOrganisations.map((item) => ({ ...item }));
  const assignments = baseAssignments.map((item) => ({ ...item }));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    calls.push({ url, init });

    if (url === "/api/platform/overview") return jsonResponse(overview);
    if (url === "/api/platform/organisations" && (!init?.method || init.method === "GET")) {
      return jsonResponse({ count: organisations.length, organisations });
    }
    if (url.startsWith("/api/platform/organisations/") && init?.method === "POST") {
      const match = url.match(/\/api\/platform\/organisations\/([^/]+)\/(suspend|reactivate)$/);
      if (match) {
        const org = organisations.find((item) => item.id === match[1]);
        if (org) {
          org.status = match[2] === "suspend" ? "suspended" : "active";
          org.is_active = match[2] === "reactivate";
        }
        return jsonResponse({ organisation_id: match[1], status: match[2] === "suspend" ? "suspended" : "active", is_active: match[2] === "reactivate" });
      }
    }
    if (url.startsWith("/api/platform/users?") && (!init?.method || init.method === "GET")) {
      if (options.searchStatus && options.searchStatus !== 200) return jsonResponse({ detail: "User search is not permitted." }, options.searchStatus);
      return jsonResponse({ count: 1, users: [{ id: "user-1", email: "owner@example.test", is_active: true }] });
    }
    if (url === "/api/platform/users/roles" && (!init?.method || init.method === "GET")) {
      return jsonResponse({ count: assignments.length, assignments });
    }
    if (url === "/api/platform/users/roles" && init?.method === "POST") {
      return jsonResponse({ user_id: "user-1", role: "platform_tenant_approver", already_assigned: false }, 201);
    }
    if (url.startsWith("/api/platform/users/") && init?.method === "DELETE") {
      const match = url.match(/\/api\/platform\/users\/([^/]+)\/roles\/([^/]+)$/);
      if (match) {
        const index = assignments.findIndex((item) => item.user_id === match[1] && item.role === match[2]);
        if (index >= 0) assignments.splice(index, 1);
        return jsonResponse({ user_id: match[1], role: match[2], revoked: true });
      }
    }
    if (url.startsWith("/api/platform/audit/events")) {
      return jsonResponse({
        count: 1,
        events: [{
          id: "event-1", actor_user_id: "actor-1", organisation_id: "org-1",
          event_type: "platform.organisation_suspended", target_type: "organisation", target_id: "org-1",
          occurred_at: "2026-01-01T00:00:00Z",
          details: { action: "platform.organisation_suspended", outcome: "success", reason_code: "security_review", query_text: "private user question", document_name: "confidential.pdf" },
        }],
      });
    }
    return jsonResponse({ detail: `Unexpected test request: ${url}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

beforeEach(() => {
  setAccessToken("platform-component-test-token");
  mockPlatformSession(["organisations:read", "platform-roles:assign", "organisations:suspend", "organisations:create", "platform-audit:read"]);
});

afterEach(() => {
  cleanup();
  setAccessToken(null);
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Platform Admin Console", () => {
  it("loads the aggregate platform overview without requesting tenant content", async () => {
    const { calls } = setupFetch();
    render(<PlatformAdmin />);
    await screen.findByRole("heading", { name: "Platform overview" });
    expect(await screen.findByText("12", { selector: ".metric-value" })).toBeTruthy();
    expect(screen.getByText("240", { selector: ".metric-value" })).toBeTruthy();
    expect(calls.some((call) => call.url === "/api/platform/overview")).toBe(true);
    expect(calls.some((call) => call.url.includes("/api/documents") || call.url.includes("/api/query"))).toBe(false);
  });

  it("suspends a tenant with confirmation and a required reason code, then refreshes lifecycle state", async () => {
    const { calls } = setupFetch();
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("prompt", vi.fn(() => "security_review"));
    render(<PlatformAdmin />);
    fireEvent.click(screen.getByRole("tab", { name: "Tenant lifecycle" }));
    await screen.findByText("North Research");
    fireEvent.click(screen.getByRole("button", { name: "Suspend tenant" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("North Research: suspended."));
    const action = calls.find((call) => call.url === "/api/platform/organisations/org-active/suspend");
    expect(action?.init?.method).toBe("POST");
    expect(JSON.parse(String(action?.init?.body))).toEqual({ reason_code: "security_review" });
  });

  it("searches for a user and submits the selected platform role", async () => {
    const { calls } = setupFetch();
    render(<PlatformAdmin />);
    fireEvent.click(screen.getByRole("tab", { name: "Access & roles" }));
    await screen.findByRole("heading", { name: "Platform role holders" });

    fireEvent.change(screen.getByLabelText("Search users by email"), { target: { value: "owner" } });
    fireEvent.click(screen.getByRole("button", { name: "Search users" }));
    const account = await screen.findByLabelText("Account");
    expect(account.textContent).toContain("owner@example.test");
    fireEvent.change(account, { target: { value: "user-1" } });
    fireEvent.change(screen.getByLabelText("Platform role"), { target: { value: "platform_tenant_approver" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign platform role" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Assigned platform_tenant_approver to owner@example.test."));

    const searchCall = calls.find((call) => call.url.startsWith("/api/platform/users?"));
    expect(searchCall?.url).toBe("/api/platform/users?q=owner&limit=25");
    const assignmentCall = calls.find((call) => call.url === "/api/platform/users/roles" && call.init?.method === "POST");
    expect(JSON.parse(String(assignmentCall?.init?.body))).toEqual({ user_id: "user-1", role: "platform_tenant_approver" });
  });

  it("lists role holders and revokes a selected non-super-admin role", async () => {
    const { calls } = setupFetch();
    vi.stubGlobal("confirm", vi.fn(() => true));
    render(<PlatformAdmin />);
    fireEvent.click(screen.getByRole("tab", { name: "Access & roles" }));
    expect(await screen.findByText("owner@example.test")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Revoke role" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Revoked Tenant creator from owner@example.test."));
    expect(calls.some((call) => call.url === "/api/platform/users/user-1/roles/platform_tenant_creator" && call.init?.method === "DELETE")).toBe(true);
  });

  it("renders the sanitized platform audit feed and never displays private payload fields", async () => {
    setupFetch();
    render(<PlatformAdmin />);
    fireEvent.click(screen.getByRole("tab", { name: "Platform audit" }));
    expect(await screen.findByText("platform.organisation_suspended")).toBeTruthy();
    expect(screen.getByText("security_review")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private user question");
    expect(document.body.textContent).not.toContain("confidential.pdf");
  });

  it("hides role and audit tabs when the session lacks their permissions", async () => {
    mockPlatformSession(["organisations:read"]);
    setupFetch();
    render(<PlatformAdmin />);
    await screen.findByRole("heading", { name: "Platform overview" });
    expect(screen.queryByRole("tab", { name: "Access & roles" })).toBeNull();
    expect(screen.queryByRole("tab", { name: "Platform audit" })).toBeNull();
  });
});
