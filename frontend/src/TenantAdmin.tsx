import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ApiRequestError,
  createTenantInvitation,
  getTenantAuditEvents,
  getTenantInvitations,
  getTenantMembers,
  getTenantOverview,
  getTenantSettings,
  removeTenantMember,
  revokeTenantInvitation,
  updateTenantMember,
  updateTenantSettings,
} from "./api/client";
import type {
  TenantAuditEvent,
  TenantInvitation,
  TenantMember,
  TenantOverviewResponse,
  TenantRole,
  TenantSettings,
} from "./api/types";
import { Icon } from "./Icons";
import { useAuth } from "./AuthContext";

type TenantAdminTab = "overview" | "members" | "audit" | "security";

const roleOptions: { value: TenantRole; label: string }[] = [
  { value: "organisation_administrator", label: "Administrator" },
  { value: "contributor", label: "Contributor" },
  { value: "reader", label: "Reader" },
];

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function roleLabel(role: TenantRole): string {
  return roleOptions.find((item) => item.value === role)?.label ?? role;
}

function protectSpreadsheetFormula(value: string): string {
  // Spreadsheet applications may evaluate cells whose first non-whitespace character
  // is a formula marker. Apply the same protection to nested JSON string values.
  return /^[\s\u0000-\u001f]*[=+@\-]/.test(value) ? `'${value}` : value;
}

function csvCell(value: unknown): string {
  let text: string;
  if (value === null || value === undefined) {
    text = "";
  } else if (typeof value === "string") {
    text = protectSpreadsheetFormula(value);
  } else {
    try {
      text = JSON.stringify(value, (_key, nested: unknown) =>
        typeof nested === "string" ? protectSpreadsheetFormula(nested) : nested,
      ) ?? String(value);
    } catch {
      // Details should normally be JSON-compatible, but a malformed value must
      // not prevent the rest of the audit log from being exported.
      text = String(value);
    }
    text = protectSpreadsheetFormula(text);
  }
  return `"${text.replaceAll('"', '""')}"`;
}

export function tenantAuditCsv(events: TenantAuditEvent[]): string {
  const headers = ["Event ID", "Occurred at", "Actor user ID", "Event", "Target type", "Target ID", "Details"];
  const rows = events.map((event) => [event.id, event.occurred_at, event.actor_user_id, event.event_type, event.target_type, event.target_id, event.details]);
  return [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

function downloadAuditCsv(events: TenantAuditEvent[]) {
  const blob = new Blob(["\uFEFF", tenantAuditCsv(events)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `ekip-tenant-audit-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function TenantAdmin() {
  const auth = useAuth();
  const permissions = useMemo(() => new Set(auth.profile?.permissions ?? []), [auth.profile?.permissions]);
  const canManageMembers = permissions.has("members:manage");
  const canReadAudit = permissions.has("audit:read");
  const canConfigureAuth = permissions.has("auth:configure");
  const visibleTabs = useMemo(() => [
    { id: "overview" as const, label: "Overview", visible: permissions.has("tenant:read") },
    { id: "members" as const, label: "Members & invitations", visible: canManageMembers },
    { id: "audit" as const, label: "Audit log", visible: canReadAudit },
    { id: "security" as const, label: "Security settings", visible: canConfigureAuth },
  ].filter((tab) => tab.visible), [permissions, canManageMembers, canReadAudit, canConfigureAuth]);

  const [activeTab, setActiveTab] = useState<TenantAdminTab>("overview");
  const [overview, setOverview] = useState<TenantOverviewResponse | null>(null);
  const [members, setMembers] = useState<TenantMember[]>([]);
  const [invitations, setInvitations] = useState<TenantInvitation[]>([]);
  const [auditEvents, setAuditEvents] = useState<TenantAuditEvent[]>([]);
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [domainsText, setDomainsText] = useState("");
  const [idleTimeout, setIdleTimeout] = useState("60");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<TenantRole>("reader");
  const [invitationToken, setInvitationToken] = useState<string | null>(null);
  const [invitationExpiry, setInvitationExpiry] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [busyMemberId, setBusyMemberId] = useState<string | null>(null);
  const [busyInvitationId, setBusyInvitationId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(visibleTabs[0]?.id ?? "overview");
    }
  }, [activeTab, visibleTabs]);

  const loadOverview = useCallback(async () => {
    setLoading(true); setError("");
    try { setOverview(await getTenantOverview()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load organisation overview."); }
    finally { setLoading(false); }
  }, []);

  const loadMembers = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [memberResult, invitationResult] = await Promise.all([getTenantMembers(), getTenantInvitations()]);
      setMembers(memberResult.members);
      setInvitations(invitationResult.invitations);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load organisation members."); }
    finally { setLoading(false); }
  }, []);

  const loadAudit = useCallback(async () => {
    setLoading(true); setError("");
    try { setAuditEvents((await getTenantAuditEvents({ limit: 100 })).events); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load the audit log."); }
    finally { setLoading(false); }
  }, []);

  const loadSettings = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const result = await getTenantSettings();
      setSettings(result);
      setDomainsText(result.allowed_email_domains.join("\n"));
      setIdleTimeout(String(result.session_idle_timeout_minutes));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load security settings."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    if (activeTab === "overview" && permissions.has("tenant:read")) void loadOverview();
    if (activeTab === "members" && canManageMembers) void loadMembers();
    if (activeTab === "audit" && canReadAudit) void loadAudit();
    if (activeTab === "security" && canConfigureAuth) void loadSettings();
  }, [activeTab, permissions, canManageMembers, canReadAudit, canConfigureAuth, loadOverview, loadMembers, loadAudit, loadSettings]);

  async function handleInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitting(true); setError(""); setNotice(""); setInvitationToken(null);
    try {
      const result = await createTenantInvitation({ recipient_email: inviteEmail.trim().toLowerCase(), role: inviteRole });
      setInviteEmail("");
      setInvitationToken(result.invitation_token);
      setInvitationExpiry(result.expires_at);
      setNotice(result.invitation_token
        ? "Invitation created. The token is exposed by this non-production environment; share it only through an approved secure channel."
        : "Invitation created. Follow your configured delivery process to notify the recipient.");
      setInvitations((current) => [{ id: result.id, recipient_email: result.recipient_email, role: result.role, invited_by_email: auth.profile?.email ?? "Current administrator", expires_at: result.expires_at, created_at: new Date().toISOString() }, ...current]);
    } catch (cause) {
      setError(cause instanceof ApiRequestError || cause instanceof Error ? cause.message : "Could not create the invitation.");
    } finally { setSubmitting(false); }
  }

  async function handleUpdateMember(member: TenantMember, change: { role?: TenantRole; is_active?: boolean }) {
    setBusyMemberId(member.id); setError(""); setNotice("");
    try {
      await updateTenantMember(member.id, change);
      setNotice(`Updated access for ${member.email}.`);
      await loadMembers();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not update the member."); }
    finally { setBusyMemberId(null); }
  }

  async function handleRemoveMember(member: TenantMember) {
    if (!window.confirm(`Remove ${member.email} from this organisation? Their active sessions will be revoked.`)) return;
    setBusyMemberId(member.id); setError(""); setNotice("");
    try {
      await removeTenantMember(member.id);
      setNotice(`Removed ${member.email} from this organisation.`);
      await loadMembers();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not remove the member."); }
    finally { setBusyMemberId(null); }
  }

  async function handleRevokeInvitation(invitation: TenantInvitation) {
    if (!window.confirm(`Revoke the pending invitation for ${invitation.recipient_email}?`)) return;
    setBusyInvitationId(invitation.id); setError(""); setNotice("");
    try {
      await revokeTenantInvitation(invitation.id);
      setInvitations((current) => current.filter((item) => item.id !== invitation.id));
      setNotice(`Revoked the invitation for ${invitation.recipient_email}.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not revoke the invitation."); }
    finally { setBusyInvitationId(null); }
  }

  async function handleSaveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitting(true); setError(""); setNotice("");
    const minutes = Number(idleTimeout);
    if (!Number.isInteger(minutes) || minutes < 5 || minutes > 1440) {
      setSubmitting(false); setError("Session idle timeout must be a whole number between 5 and 1,440 minutes."); return;
    }
    const domains = domainsText.split(/[\n,]/).map((item) => item.trim().toLowerCase().replace(/^@/, "")).filter(Boolean);
    try {
      const updated = await updateTenantSettings({ allowed_email_domains: [...new Set(domains)], session_idle_timeout_minutes: minutes });
      setSettings(updated);
      setDomainsText(updated.allowed_email_domains.join("\n"));
      setIdleTimeout(String(updated.session_idle_timeout_minutes));
      setNotice("Organisation security settings saved.");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save security settings."); }
    finally { setSubmitting(false); }
  }

  const refreshActiveTab = () => {
    if (activeTab === "overview") void loadOverview();
    if (activeTab === "members") void loadMembers();
    if (activeTab === "audit") void loadAudit();
    if (activeTab === "security") void loadSettings();
  };

  return <main className="page-section tenant-page">
    <section className="compact-heading">
      <div><p className="eyebrow">ORGANISATION MANAGEMENT</p><h1 tabIndex={-1}>Organisation administration</h1><p>Manage your organisation's members, access rules and audit history. Available actions depend on your organisation permissions.</p></div>
      <button className="secondary-button" type="button" onClick={refreshActiveTab} disabled={loading}><Icon name="refresh"/>{loading ? "Refreshing…" : "Refresh"}</button>
    </section>

    <nav className="tenant-tabs" aria-label="Organisation administration sections">
      {visibleTabs.map((tab) => <button key={tab.id} type="button" aria-current={activeTab === tab.id ? "page" : undefined} onClick={() => { setActiveTab(tab.id); setError(""); setNotice(""); }}>{tab.label}</button>)}
    </nav>

    {error && <div className="inline-error" role="alert">{error} <button type="button" className="text-button" onClick={refreshActiveTab}>Try again</button></div>}
    {notice && <div className="platform-notice" role="status">{notice}</div>}

    {activeTab === "overview" && <TenantOverviewPanel overview={overview} loading={loading} />}

    {activeTab === "members" && <section className="tenant-panel">
      <div className="tenant-panel-heading"><div><p className="eyebrow">PEOPLE & ACCESS</p><h2>Members</h2><p>Manage membership roles and active access. Removing a member revokes their active sessions.</p></div><span className="platform-count">{members.length} members</span></div>
      {loading ? <p className="tenant-muted" role="status">Loading members…</p> : members.length === 0 ? <p className="tenant-empty">No members were returned for this organisation.</p> : <div className="desktop-table-wrap"><table className="document-table tenant-table"><thead><tr><th>Member</th><th>Role</th><th>Status</th><th>Member since</th><th>Actions</th></tr></thead><tbody>{members.map((member) => <TenantMemberRow key={member.id} member={member} busy={busyMemberId === member.id} onUpdate={handleUpdateMember} onRemove={handleRemoveMember}/>)}</tbody></table></div>}

      <div className="tenant-subsection"><div className="tenant-panel-heading"><div><p className="eyebrow">INVITE A COLLEAGUE</p><h2>New invitation</h2><p>Invitations are organisation-scoped, expire after seven days and can be revoked before acceptance.</p></div></div>
        <form className="tenant-form tenant-invite-form" onSubmit={(event) => void handleInvite(event)}>
          <div className="tenant-invite-email-field">
            <label htmlFor="tenant-invitation-email">Work email</label>
            <input id="tenant-invitation-email" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} required maxLength={320} autoComplete="off" placeholder="colleague@example.org" aria-describedby="tenant-invitation-email-help"/>
            <small id="tenant-invitation-email-help">Invitation creation requires configured email delivery or explicit non-production token exposure.</small>
          </div>
          <label>Organisation role<select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as TenantRole)}>{roleOptions.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
          <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Creating invitation…" : "Create invitation"}</button>
        </form>
        {invitationToken && <div className="tenant-token" aria-label="Development invitation token"><strong>One-time invitation token</strong><code>{invitationToken}</code><small>Expires {formatDate(invitationExpiry)}. This token is visible because the current non-production API explicitly allows token exposure. Do not post it in tickets or public channels.</small></div>}
      </div>

      <div className="tenant-subsection"><div className="tenant-panel-heading"><div><p className="eyebrow">AWAITING ACCEPTANCE</p><h2>Pending invitations</h2></div><span className="platform-count">{invitations.length} pending</span></div>
        {loading ? <p className="tenant-muted">Loading invitations…</p> : invitations.length === 0 ? <p className="tenant-empty">There are no pending invitations.</p> : <div className="desktop-table-wrap"><table className="document-table tenant-table"><thead><tr><th>Recipient</th><th>Role</th><th>Invited by</th><th>Expires</th><th>Actions</th></tr></thead><tbody>{invitations.map((invitation) => <tr key={invitation.id}><th scope="row">{invitation.recipient_email}</th><td>{roleLabel(invitation.role)}</td><td>{invitation.invited_by_email}</td><td>{formatDate(invitation.expires_at)}</td><td><button type="button" className="danger-button tenant-small-action" disabled={busyInvitationId === invitation.id} onClick={() => void handleRevokeInvitation(invitation)}>{busyInvitationId === invitation.id ? "Revoking…" : "Revoke"}</button></td></tr>)}</tbody></table></div>}
      </div>
    </section>}

    {activeTab === "audit" && <section className="tenant-panel">
      <div className="tenant-panel-heading"><div><p className="eyebrow">ORGANISATION ACTIVITY</p><h2>Audit log</h2><p>Recent events recorded for this organisation. The API scopes this feed to your current membership.</p></div><button className="secondary-button" type="button" onClick={() => downloadAuditCsv(auditEvents)} disabled={auditEvents.length === 0}>Export visible events (CSV)</button></div>
      {loading ? <p className="tenant-muted" role="status">Loading audit events…</p> : auditEvents.length === 0 ? <p className="tenant-empty">No audit events are available.</p> : <div className="tenant-audit-list">{auditEvents.map((event) => <article className="tenant-audit-item" key={event.id}><div className="tenant-audit-main"><div><strong>{event.event_type.replaceAll(".", " · ").replaceAll("_", " ")}</strong><small>{event.target_type ?? "Organisation event"}{event.target_id ? ` · ${event.target_id}` : ""}</small></div><time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time></div><dl>{Object.entries(event.details).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value ?? "—")}</dd></div>)}</dl></article>)}</div>}
      <p className="tenant-footnote">Showing up to the 100 most recent events. CSV export includes only the events currently displayed.</p>
    </section>}

    {activeTab === "security" && <section className="tenant-panel">
      <div className="tenant-panel-heading"><div><p className="eyebrow">SIGN-IN POLICY</p><h2>Security settings</h2><p>Control permitted invitation domains and the idle lifetime of tenant sessions.</p></div></div>
      <form className="tenant-settings-form" onSubmit={(event) => void handleSaveSettings(event)}>
        <label>Allowed email domains <span>One domain per line or separated by commas. Leave empty to allow any valid email domain.</span><textarea rows={5} value={domainsText} onChange={(event) => setDomainsText(event.target.value)} placeholder={"example.org\npartner.example.org"}/></label>
        <label>Session idle timeout (minutes)<span>Between 5 and 1,440 minutes. This is enforced for tenant sessions during authentication and refresh.</span><input type="number" min={5} max={1440} step={1} value={idleTimeout} onChange={(event) => setIdleTimeout(event.target.value)} required/></label>
        <button className="primary-button" type="submit" disabled={submitting || loading}>{submitting ? "Saving settings…" : "Save security settings"}</button>
      </form>
      {settings && <p className="tenant-footnote">Settings belong to {auth.profile?.organisation?.name ?? "this organisation"}. Changes are recorded in the tenant audit log.</p>}
    </section>}
  </main>;
}

function TenantOverviewPanel({ overview, loading }: { overview: TenantOverviewResponse | null; loading: boolean }) {
  const metric = (label: string, value: number | undefined, hint: string, icon: "document" | "chunks" | "attention" | "overview") => <article className="metric-card"><div className="metric-topline"><span>{label}</span><span className="metric-icon"><Icon name={icon}/></span></div><strong className="metric-value">{loading || typeof value !== "number" ? "—" : value.toLocaleString()}</strong><span className="metric-caption">{hint}</span></article>;
  return <section className="tenant-panel"><div className="tenant-panel-heading"><div><p className="eyebrow">TENANT OVERVIEW</p><h2>{overview?.organisation_name ?? "Organisation overview"}</h2><p>Operational counters for your organisation only.</p></div></div><div className="metrics-grid tenant-metrics">
    {metric("Indexed documents", overview?.document_count, "Documents in this organisation", "document")}
    {metric("Indexed chunks", overview?.chunk_count, "Searchable passages", "chunks")}
    {metric("Active members", overview?.member_count, "Current organisation membership", "overview")}
    {metric("Failed documents", overview?.failed_document_count, "Documents requiring attention", "attention")}
  </div></section>;
}

function TenantMemberRow({ member, busy, onUpdate, onRemove }: {
  member: TenantMember;
  busy: boolean;
  onUpdate: (member: TenantMember, change: { role?: TenantRole; is_active?: boolean }) => Promise<void>;
  onRemove: (member: TenantMember) => Promise<void>;
}) {
  const [role, setRole] = useState<TenantRole>(member.role);
  useEffect(() => setRole(member.role), [member.role]);
  const changed = role !== member.role;
  return <tr><th scope="row"><span className="tenant-member-email">{member.email}</span><small>{member.user_id}</small></th><td><select aria-label={`Role for ${member.email}`} value={role} onChange={(event) => setRole(event.target.value as TenantRole)} disabled={busy}>{roleOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></td><td><span className={`platform-status ${member.is_active ? "platform-status--active" : "platform-status--suspended"}`}>{member.is_active ? "Active" : "Inactive"}</span></td><td>{formatDate(member.created_at)}</td><td><div className="tenant-row-actions">{changed && <button type="button" className="secondary-button tenant-small-action" disabled={busy} onClick={() => void onUpdate(member, { role })}>Save role</button>}<button type="button" className="secondary-button tenant-small-action" disabled={busy} onClick={() => void onUpdate(member, { is_active: !member.is_active })}>{member.is_active ? "Deactivate" : "Reactivate"}</button><button type="button" className="danger-button tenant-small-action" disabled={busy} onClick={() => void onRemove(member)}>Remove</button></div></td></tr>;
}
