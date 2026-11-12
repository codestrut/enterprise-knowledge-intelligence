import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const { mockUseAuth } = vi.hoisted(() => ({ mockUseAuth: vi.fn() }));
vi.mock("./AuthContext", () => ({ useAuth: mockUseAuth }));

import TenantAdmin, { tenantAuditCsv } from "./TenantAdmin";
import { setAccessToken } from "./api/client";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const overview = {
  organisation_id: "org-1", organisation_name: "Research Group", document_count: 12,
  chunk_count: 840, failed_document_count: 1, member_count: 4,
};

function setupFetch() {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url === "/api/tenant/overview") return response(overview);
    if (url === "/api/tenant/members") return response({ count: 2, members: [
      { id: "membership-1", user_id: "user-1", email: "admin@example.test", role: "organisation_administrator", is_active: true, created_at: "2026-01-01T00:00:00Z" },
      { id: "membership-2", user_id: "user-2", email: "reader@example.test", role: "reader", is_active: true, created_at: "2026-01-02T00:00:00Z" },
    ] });
    if (url === "/api/tenant/members/invitations" && init?.method === "POST") return response({ id: "invite-2", recipient_email: "new@example.test", role: "reader", invitation_token: "dev-only-token", expires_at: "2026-01-08T00:00:00Z" }, 201);
    if (url === "/api/tenant/members/invitations") return response({ count: 1, invitations: [
      { id: "invite-1", recipient_email: "pending@example.test", role: "contributor", invited_by_email: "admin@example.test", expires_at: "2026-01-08T00:00:00Z", created_at: "2026-01-01T00:00:00Z" },
    ] });
    if (url === "/api/tenant/settings" && init?.method === "PATCH") return response({ organisation_id: "org-1", allowed_email_domains: ["example.test", "partner.test"], session_idle_timeout_minutes: 90 });
    if (url === "/api/tenant/settings") return response({ organisation_id: "org-1", allowed_email_domains: ["example.test"], session_idle_timeout_minutes: 60 });
    if (url.startsWith("/api/audit/events")) return response({ count: 1, events: [
      { id: "event-1", actor_user_id: "user-1", organisation_id: "org-1", event_type: "tenant.member_updated", target_type: "membership", target_id: "membership-2", occurred_at: "2026-01-03T10:00:00Z", details: { action: "tenant.member_updated", outcome: "success", role: "reader" } },
    ] });
    if (url === "/api/tenant/members/membership-2" && init?.method === "PATCH") return response({ id: "membership-2", user_id: "user-2", role: "contributor", is_active: true });
    return response({ detail: `Unexpected request: ${url}` }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function session(permissions: string[]) {
  mockUseAuth.mockReturnValue({
    profile: { email: "admin@example.test", organisation: { id: "org-1", name: "Research Group" }, permissions },
  });
}

beforeEach(() => {
  setAccessToken("tenant-admin-test-token");
  session(["tenant:read", "members:manage", "audit:read", "auth:configure"]);
});

afterEach(() => {
  cleanup();
  setAccessToken(null);
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("Tenant Admin Portal", () => {
  it("loads tenant-only overview metrics and exposes tabs only for granted permissions", async () => {
    const { calls } = setupFetch();
    render(<TenantAdmin />);

    expect(await screen.findByRole("heading", { name: "Research Group" })).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("840")).toBeTruthy();
    expect(screen.getByText("4")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Members & invitations" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Audit log" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Security settings" })).toBeTruthy();
    expect(calls.some((call) => call.url === "/api/tenant/overview")).toBe(true);
  });

  it("does not request member, audit or settings data when the session has overview permission only", async () => {
    session(["tenant:read"]);
    const { calls } = setupFetch();
    render(<TenantAdmin />);

    expect(await screen.findByRole("heading", { name: "Research Group" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Members & invitations" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Audit log" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Security settings" })).toBeNull();
    expect(calls.some((call) => call.url.includes("/api/tenant/members"))).toBe(false);
    expect(calls.some((call) => call.url.startsWith("/api/audit/events"))).toBe(false);
    expect(calls.some((call) => call.url === "/api/tenant/settings")).toBe(false);
  });

  it("loads members and pending invitations, then creates an invitation without sending a custom message", async () => {
    const { calls } = setupFetch();
    render(<TenantAdmin />);
    fireEvent.click(screen.getByRole("button", { name: "Members & invitations" }));

    expect(await screen.findByText("reader@example.test")).toBeTruthy();
    expect(screen.getByText("pending@example.test")).toBeTruthy();
    const workEmail = screen.getByLabelText("Work email");
    expect(workEmail.getAttribute("aria-describedby")).toBe("tenant-invitation-email-help");
    fireEvent.change(workEmail, { target: { value: "new@example.test" } });
    fireEvent.change(screen.getByLabelText("Organisation role"), { target: { value: "reader" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invitation" }));

    expect(await screen.findByText("dev-only-token")).toBeTruthy();
    const inviteCall = calls.find((call) => call.url === "/api/tenant/members/invitations" && call.init?.method === "POST");
    expect(inviteCall?.init?.method).toBe("POST");
    expect(JSON.parse(String(inviteCall?.init?.body))).toEqual({ recipient_email: "new@example.test", role: "reader" });
    expect(String(inviteCall?.init?.body)).not.toContain("message");
  });

  it("sends role changes through the tenant member PATCH endpoint", async () => {
    const { calls } = setupFetch();
    render(<TenantAdmin />);
    fireEvent.click(screen.getByRole("button", { name: "Members & invitations" }));
    const roleSelect = await screen.findByLabelText("Role for reader@example.test");
    fireEvent.change(roleSelect, { target: { value: "contributor" } });
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));

    await waitFor(() => expect(calls.some((call) => call.url === "/api/tenant/members/membership-2" && call.init?.method === "PATCH")).toBe(true));
    const patch = calls.find((call) => call.url === "/api/tenant/members/membership-2" && call.init?.method === "PATCH");
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ role: "contributor" });
  });

  it("loads security settings and saves allowed domains and the enforced idle timeout", async () => {
    const { calls } = setupFetch();
    render(<TenantAdmin />);
    fireEvent.click(screen.getByRole("button", { name: "Security settings" }));
    expect(await screen.findByLabelText(/Allowed email domains/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Allowed email domains/), { target: { value: "example.test\npartner.test" } });
    fireEvent.change(screen.getByLabelText(/Session idle timeout \(minutes\)/), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Save security settings" }));

    await waitFor(() => expect(calls.some((call) => call.url === "/api/tenant/settings" && call.init?.method === "PATCH")).toBe(true));
    const patch = calls.find((call) => call.url === "/api/tenant/settings" && call.init?.method === "PATCH");
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ allowed_email_domains: ["example.test", "partner.test"], session_idle_timeout_minutes: 90 });
  });

  it("renders the tenant audit feed and protects CSV exports against spreadsheet formulas", async () => {
    setupFetch();
    render(<TenantAdmin />);
    fireEvent.click(screen.getByRole("button", { name: "Audit log" }));
    expect(await screen.findByText(/tenant · member updated/i)).toBeTruthy();
    const csv = tenantAuditCsv([{
      id: "event-2", actor_user_id: null, organisation_id: "org-1",
      event_type: "=HYPERLINK(\"https://event-bad.test\")",
      target_type: null, target_id: null, occurred_at: "2026-01-01T00:00:00Z",
      details: { value: "=HYPERLINK(\"https://bad.test\")", nested: ["+SUM(1,2)", "@SUM(1,2)"] },
    }]);
    expect(csv).toContain("'=HYPERLINK(");
    expect(csv).toContain("'+SUM(");
    expect(csv).toContain("'@SUM(");
  });
});
