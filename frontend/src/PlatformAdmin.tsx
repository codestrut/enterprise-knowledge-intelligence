import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  ApiRequestError,
  approvePlatformOrganisation,
  assignPlatformRole,
  createPlatformOrganisation,
  getPlatformAuditEvents,
  getPlatformOrganisations,
  getPlatformOverview,
  getPlatformRoleHolders,
  reactivatePlatformOrganisation,
  recoverPlatformProvisioning,
  retryPlatformProvisioning,
  revokePlatformRole,
  searchPlatformUsers,
  suspendPlatformOrganisation,
} from "./api/client";
import type {
  PlatformAuditEvent,
  PlatformOrganisation,
  PlatformOverviewResponse,
  PlatformRole,
  PlatformRoleHolder,
  PlatformUser,
} from "./api/types";
import { Icon } from "./Icons";
import { useAuth } from "./AuthContext";
import { navigate } from "./routing";

type PlatformTab = "overview" | "tenants" | "access" | "audit";
type LifecycleAction = "approve" | "retry" | "recover" | "suspend" | "reactivate";

const permissionLabels: Record<string, string> = {
  "organisations:read": "View platform overview and tenants",
  "organisations:create": "Create tenant registrations",
  "organisations:approve": "Approve tenant onboarding",
  "organisations:provisioning-retry": "Retry provisioning",
  "organisations:provisioning-recover": "Recover stale provisioning",
  "organisations:suspend": "Suspend and reactivate tenants",
  "platform-roles:assign": "Manage platform roles",
  "platform-users:manage": "Manage platform users",
  "platform-audit:read": "Read sanitized platform audit",
};

const platformRoleOptions: { value: PlatformRole; label: string }[] = [
  { value: "platform_tenant_creator", label: "Tenant creator" },
  { value: "platform_tenant_approver", label: "Tenant approver" },
  { value: "platform_provisioning_operator", label: "Provisioning operator" },
  { value: "platform_super_administrator", label: "Super administrator" },
];

const tabs: { id: PlatformTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "tenants", label: "Tenant lifecycle" },
  { id: "access", label: "Access & roles" },
  { id: "audit", label: "Platform audit" },
];

const platformTabPaths: Record<PlatformTab, string> = {
  overview: "/platform",
  tenants: "/platform/organisations",
  access: "/platform/access",
  audit: "/platform/audit",
};

function platformTabFromPath(pathname: string): PlatformTab {
  const match = Object.entries(platformTabPaths).find(([, route]) => route === pathname);
  return (match?.[0] as PlatformTab | undefined) ?? "overview";
}

function statusLabel(status: string) { return status.replaceAll("_", " "); }
function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function roleLabel(role: PlatformRole) {
  return platformRoleOptions.find((item) => item.value === role)?.label ?? statusLabel(role);
}

export default function PlatformAdmin({ pathname }: { pathname?: string } = {}) {
  const auth = useAuth();
  const permissions = useMemo(() => new Set(auth.profile?.platform_permissions ?? []), [auth.profile?.platform_permissions]);
  const canRead = permissions.has("organisations:read");
  const canCreate = permissions.has("organisations:create");
  const canAssignRoles = permissions.has("platform-roles:assign");
  const canApprove = permissions.has("organisations:approve");
  const canRetry = permissions.has("organisations:provisioning-retry");
  const canRecover = permissions.has("organisations:provisioning-recover");
  const canSuspend = permissions.has("organisations:suspend");
  const canReadAudit = permissions.has("platform-audit:read");
  const visibleTabs = useMemo(() => tabs.filter((tab) => {
    if (tab.id === "overview" || tab.id === "tenants") return canRead;
    if (tab.id === "access") return canAssignRoles;
    return canReadAudit;
  }), [canRead, canAssignRoles, canReadAudit]);

  const [localActiveTab, setLocalActiveTab] = useState<PlatformTab>("overview");
  const activeTab = pathname ? platformTabFromPath(pathname) : localActiveTab;

  function selectTab(tab: PlatformTab) {
    if (pathname) {
      navigate(platformTabPaths[tab]);
    } else {
      setLocalActiveTab(tab);
    }
  }
  const [overview, setOverview] = useState<PlatformOverviewResponse | null>(null);
  const [organisations, setOrganisations] = useState<PlatformOrganisation[]>([]);
  const [assignments, setAssignments] = useState<PlatformRoleHolder[]>([]);
  const [auditEvents, setAuditEvents] = useState<PlatformAuditEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [adminEmail, setAdminEmail] = useState("");

  const [userQuery, setUserQuery] = useState("");
  const [userResults, setUserResults] = useState<PlatformUser[]>([]);
  const [selectedUserId, setSelectedUserId] = useState("");
  const [selectedRole, setSelectedRole] = useState<PlatformRole>("platform_tenant_creator");
  const [hasSearchedUsers, setHasSearchedUsers] = useState(false);
  const [searchingUsers, setSearchingUsers] = useState(false);
  const [assigningRole, setAssigningRole] = useState(false);
  const [roleFeedback, setRoleFeedback] = useState("");
  const [roleFeedbackIsError, setRoleFeedbackIsError] = useState(false);

  useEffect(() => {
    if (!pathname && !visibleTabs.some((tab) => tab.id === activeTab)) {
      setLocalActiveTab(visibleTabs[0]?.id ?? "overview");
    }
  }, [pathname, activeTab, visibleTabs]);

  const loadOverview = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try { setOverview(await getPlatformOverview()); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load platform overview."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  const loadOrganisations = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try { setOrganisations((await getPlatformOrganisations()).organisations); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load platform tenants."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  const loadAssignments = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try { setAssignments((await getPlatformRoleHolders()).assignments); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load platform role assignments."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  const loadAudit = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    setError("");
    try { setAuditEvents((await getPlatformAuditEvents({ limit: 100 })).events); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load platform audit events."); }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => {
    if (activeTab === "overview" && canRead) void loadOverview();
    if (activeTab === "tenants" && canRead) void loadOrganisations();
    if (activeTab === "access" && canAssignRoles) void loadAssignments();
    if (activeTab === "audit" && canReadAudit) void loadAudit();
  }, [activeTab, canRead, canAssignRoles, canReadAudit, loadOverview, loadOrganisations, loadAssignments, loadAudit]);

  const refreshActive = useCallback(() => {
    if (activeTab === "overview") return loadOverview(true);
    if (activeTab === "tenants") return loadOrganisations(true);
    if (activeTab === "access") return loadAssignments(true);
    return loadAudit(true);
  }, [activeTab, loadOverview, loadOrganisations, loadAssignments, loadAudit]);

  async function createTenant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSubmitting(true); setError(""); setNotice("");
    try {
      await createPlatformOrganisation({ name: name.trim(), slug: slug.trim(), initial_admin_email: adminEmail.trim().toLowerCase() }, crypto.randomUUID());
      setName(""); setSlug(""); setAdminEmail("");
      setNotice("Tenant registration created. It remains inactive until explicitly approved and provisioned.");
      await loadOrganisations(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create tenant registration."); }
    finally { setSubmitting(false); }
  }

  async function runLifecycleAction(org: PlatformOrganisation, action: LifecycleAction) {
    const labels: Record<LifecycleAction, string> = {
      approve: "Approve and begin provisioning for", retry: "Retry provisioning for", recover: "Recover stale provisioning for",
      suspend: "Suspend tenant", reactivate: "Reactivate tenant",
    };
    const confirmed = action === "suspend" || action === "reactivate"
      ? window.confirm(`${labels[action]} ${org.name}? This changes tenant access.`)
      : true;
    if (!confirmed) return;
    const reasonPrompt = action === "approve" ? "Reason code for tenant approval:" : action === "retry" ? "Reason code for retrying provisioning:" : action === "recover" ? "Reason code for provisioning recovery:" : action === "suspend" ? "Reason code for suspending this tenant:" : "Reason code for reactivating this tenant:";
    const reason = window.prompt(reasonPrompt);
    if (!reason?.trim()) return;
    setError(""); setNotice(""); setSubmitting(true);
    try {
      if (action === "approve") await approvePlatformOrganisation(org.id, reason.trim());
      if (action === "retry") await retryPlatformProvisioning(org.id, reason.trim());
      if (action === "recover") await recoverPlatformProvisioning(org.id, reason.trim());
      if (action === "suspend") await suspendPlatformOrganisation(org.id, reason.trim());
      if (action === "reactivate") await reactivatePlatformOrganisation(org.id, reason.trim());
      setNotice(`${org.name}: ${action === "suspend" ? "suspended" : action === "reactivate" ? "reactivated" : "action completed"}.`);
      await Promise.all([loadOrganisations(true), loadOverview(true)]);
    } catch (cause) {
      setError(cause instanceof ApiRequestError || cause instanceof Error ? cause.message : "The platform action could not be completed.");
    } finally { setSubmitting(false); }
  }

  async function searchUsers(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = userQuery.trim();
    setRoleFeedback(""); setRoleFeedbackIsError(false); setSelectedUserId(""); setUserResults([]); setHasSearchedUsers(false);
    if (query.length < 2) { setRoleFeedbackIsError(true); setRoleFeedback("Enter at least two characters of an email address."); return; }
    setSearchingUsers(true);
    try {
      const result = await searchPlatformUsers(query);
      setUserResults(result.users); setHasSearchedUsers(true);
      setRoleFeedback(result.users.length === 0 ? "No users matched that search." : `Found ${result.users.length} user${result.users.length === 1 ? "" : "s"}.`);
    } catch (cause) { setRoleFeedbackIsError(true); setRoleFeedback(cause instanceof Error ? cause.message : "Could not search platform users."); }
    finally { setSearchingUsers(false); }
  }

  async function assignRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const user = userResults.find((item) => item.id === selectedUserId);
    if (!user) { setRoleFeedbackIsError(true); setRoleFeedback("Select a user before assigning a role."); return; }
    setAssigningRole(true); setRoleFeedback(""); setRoleFeedbackIsError(false);
    try {
      const result = await assignPlatformRole(user.id, selectedRole);
      setRoleFeedback(result.already_assigned ? `${selectedRole} was already assigned to ${user.email}.` : `Assigned ${selectedRole} to ${user.email}.`);
      await loadAssignments(true);
    } catch (cause) { setRoleFeedbackIsError(true); setRoleFeedback(cause instanceof ApiRequestError || cause instanceof Error ? cause.message : "Could not assign the platform role."); }
    finally { setAssigningRole(false); }
  }

  async function revokeRole(assignment: PlatformRoleHolder) {
    if (!window.confirm(`Revoke ${roleLabel(assignment.role)} from ${assignment.email}? The action will be recorded in platform audit.`)) return;
    setAssigningRole(true); setRoleFeedback(""); setRoleFeedbackIsError(false);
    try {
      await revokePlatformRole(assignment.user_id, assignment.role);
      setRoleFeedback(`Revoked ${roleLabel(assignment.role)} from ${assignment.email}.`);
      await loadAssignments(true);
    } catch (cause) { setRoleFeedbackIsError(true); setRoleFeedback(cause instanceof Error ? cause.message : "Could not revoke the platform role."); }
    finally { setAssigningRole(false); }
  }

  const heading = activeTab === "overview" ? "Platform overview" : activeTab === "tenants" ? "Tenant lifecycle" : activeTab === "access" ? "Platform access and roles" : "Platform audit";

  return <main className="page-section platform-page">
    <section className="compact-heading">
      <div><p className="eyebrow">PLATFORM OPERATIONS</p><h1 tabIndex={-1}>Platform administration</h1><p>Global operational controls and aggregate tenant telemetry. Tenant documents and query content remain outside platform access.</p></div>
      <button className="secondary-button" type="button" onClick={() => void refreshActive()} disabled={refreshing || loading}><Icon name="refresh"/>{refreshing || loading ? "Refreshing" : "Refresh"}</button>
    </section>

    <section className="platform-permissions" aria-label="Your platform permissions">
      <div><p className="eyebrow">YOUR PLATFORM ACCESS</p><h2>Permissions assigned to this session</h2><p>Controls below are shown only when the session has the matching platform permission.</p></div>
      <div className="permission-chips">{(auth.profile?.platform_permissions ?? []).map((permission) => <span key={permission} className="permission-chip">{permissionLabels[permission] ?? permission}</span>)}</div>
    </section>

    <nav className="platform-tabs" role="tablist" aria-label="Platform administration sections">
      {visibleTabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} aria-current={activeTab === tab.id ? "page" : undefined} onClick={() => selectTab(tab.id)}>{tab.label}</button>)}
    </nav>

    {error && <div className="inline-error" role="alert">{error} <button type="button" className="text-button" onClick={() => void refreshActive()}>Try again</button></div>}
    {notice && <div className="platform-notice" role="status">{notice}</div>}

    {activeTab === "overview" && canRead && <section className="platform-panel" role="tabpanel" aria-label={heading}>
      <div className="platform-panel-heading"><div><p className="eyebrow">GLOBAL OPERATIONS</p><h2>{heading}</h2><p>Aggregated counts only. No document names, content, embeddings, user questions or generated answers are exposed here.</p></div><span className="platform-count">{overview ? "Current snapshot" : loading ? "Loading…" : "Unavailable"}</span></div>
      {!overview && !loading ? <p className="platform-empty">Platform overview is unavailable. Refresh to retry.</p> : <div className="metrics-grid platform-metrics platform-overview-metrics">
        <Metric label="Total tenants" value={overview?.total_tenants} loading={loading}/>
        <Metric label="Active tenants" value={overview?.active_tenants} loading={loading}/>
        <Metric label="Pending tenants" value={overview?.pending_tenants} loading={loading}/>
        <Metric label="Provisioning" value={overview?.provisioning_tenants} loading={loading}/>
        <Metric label="Provisioning failures" value={overview?.failed_tenants} loading={loading} attention/>
        <Metric label="Suspended tenants" value={overview?.suspended_tenants} loading={loading} attention/>
        <Metric label="Indexed documents" value={overview?.total_documents} loading={loading}/>
        <Metric label="Indexed chunks" value={overview?.total_chunks} loading={loading}/>
      </div>}
    </section>}

    {activeTab === "tenants" && canRead && <>
      {canCreate && <section className="platform-panel"><div className="platform-panel-heading"><div><p className="eyebrow">NEW TENANT</p><h2>Create tenant registration</h2><p>Creation does not activate an organisation. Explicit approval and provisioning are required.</p></div></div>
        <form className="platform-create-form" onSubmit={(event) => void createTenant(event)}>
          <label>Organisation name<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} placeholder="e.g. Northern Research Institute" /></label>
          <label>Tenant slug<input value={slug} onChange={(event) => setSlug(event.target.value.toLowerCase())} required maxLength={120} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="northern-research" /></label>
          <label>Initial administrator email<input type="email" value={adminEmail} onChange={(event) => setAdminEmail(event.target.value)} required maxLength={320} placeholder="admin@example.org" /></label>
          <button className="primary-button" type="submit" disabled={submitting}>{submitting ? "Creating…" : "Create registration"}</button>
        </form>
      </section>}
      <section className="platform-panel"><div className="platform-panel-heading"><div><p className="eyebrow">TENANT DIRECTORY</p><h2>Organisations</h2><p>Review lifecycle status, approve new tenants, recover provisioning, and suspend or reactivate access when authorized.</p></div><span className="platform-count">{loading ? "Loading…" : `${organisations.length} records`}</span></div>
        {loading && organisations.length === 0 ? <p className="platform-empty" role="status">Loading tenant records…</p> : organisations.length === 0 && !error ? <p className="platform-empty">No tenant records were returned for this account.</p> : <div className="desktop-table-wrap"><table className="document-table platform-table"><thead><tr><th>Organisation</th><th>Status</th><th>Initial admin</th><th>Attempts</th><th>Created</th><th>Available actions</th></tr></thead><tbody>{organisations.map((org) => <tr key={org.id}>
          <th scope="row"><span className="platform-org-name">{org.name}</span><small>{org.slug}</small></th>
          <td><span className={`platform-status platform-status--${org.status}`}>{statusLabel(org.status)}</span>{org.provisioning_error_code && <small className="platform-error-code">{org.provisioning_error_code}</small>}</td>
          <td>{org.initial_admin_email ?? "—"}</td><td>{org.provisioning_attempts}/5</td><td>{formatDate(org.created_at)}</td>
          <td><div className="platform-actions">
            {canApprove && org.status === "registration_pending" && <button type="button" className="secondary-button" disabled={submitting} onClick={() => void runLifecycleAction(org, "approve")}>Approve & provision</button>}
            {canRecover && org.status === "provisioning" && org.provisioning_started_at && <button type="button" className="secondary-button" disabled={submitting} onClick={() => void runLifecycleAction(org, "recover")}>Recover stale attempt</button>}
            {canRetry && org.status === "provisioning_failed" && org.provisioning_attempts < 5 && <button type="button" className="secondary-button" disabled={submitting} onClick={() => void runLifecycleAction(org, "retry")}>Retry provisioning</button>}
            {canSuspend && org.status === "active" && org.is_active && <button type="button" className="danger-button tenant-small-action" disabled={submitting} onClick={() => void runLifecycleAction(org, "suspend")}>Suspend tenant</button>}
            {canSuspend && org.status === "suspended" && <button type="button" className="secondary-button" disabled={submitting} onClick={() => void runLifecycleAction(org, "reactivate")}>Reactivate tenant</button>}
            {org.status === "pending_admin" && <span className="platform-no-action">Awaiting initial admin</span>}
            {!((canApprove && org.status === "registration_pending") || (canRecover && org.status === "provisioning" && org.provisioning_started_at) || (canRetry && org.status === "provisioning_failed" && org.provisioning_attempts < 5) || (canSuspend && ((org.status === "active" && org.is_active) || org.status === "suspended")) || org.status === "pending_admin") && <span className="platform-no-action">No permitted action</span>}
          </div></td>
        </tr>)}</tbody></table></div>}
      </section>
    </>}

    {activeTab === "access" && canAssignRoles && <section className="platform-panel" role="tabpanel" aria-label={heading}>
      <div className="platform-panel-heading"><div><p className="eyebrow">ACCESS CONTROL</p><h2>Assign platform roles</h2><p>Search by email, verify the account, then assign the minimum role required. Grants and revocations are audited by the API.</p></div></div>
      <form className="platform-create-form" onSubmit={(event) => void searchUsers(event)}>
        <label>Search users by email<input type="search" value={userQuery} onChange={(event) => { setUserQuery(event.target.value); setUserResults([]); setSelectedUserId(""); setHasSearchedUsers(false); setRoleFeedback(""); }} minLength={2} maxLength={320} required autoComplete="off" placeholder="e.g. admin@example.org" /></label>
        <button className="secondary-button" type="submit" disabled={searchingUsers}>{searchingUsers ? "Searching…" : "Search users"}</button>
      </form>
      {hasSearchedUsers && userResults.length > 0 && <form className="platform-create-form platform-assign-form" onSubmit={(event) => void assignRole(event)}>
        <label>Account<select required value={selectedUserId} onChange={(event) => setSelectedUserId(event.target.value)}><option value="">Select a user</option>{userResults.map((user) => <option key={user.id} value={user.id}>{user.email} — {user.is_active ? "Active" : "Inactive"}</option>)}</select></label>
        <label>Platform role<select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value as PlatformRole)}>{platformRoleOptions.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
        <button className="primary-button" type="submit" disabled={assigningRole || !selectedUserId}>{assigningRole ? "Assigning…" : "Assign platform role"}</button>
      </form>}
      {roleFeedback && <div className={roleFeedbackIsError ? "inline-error" : "platform-notice"} role={roleFeedbackIsError ? "alert" : "status"}>{roleFeedback}</div>}
      <div className="tenant-subsection"><div className="platform-panel-heading"><div><p className="eyebrow">CURRENT ASSIGNMENTS</p><h2>Platform role holders</h2><p>Only explicit platform role assignments appear here. Legacy platform-admin flags require the separately reviewed identity transition.</p></div><span className="platform-count">{assignments.length} assignments</span></div>
        {loading && assignments.length === 0 ? <p className="platform-empty" role="status">Loading role assignments…</p> : assignments.length === 0 ? <p className="platform-empty">No explicit platform role assignments were returned.</p> : <div className="desktop-table-wrap"><table className="document-table platform-table platform-roles-table"><thead><tr><th>Account</th><th>Platform role</th><th>Assigned</th><th>Action</th></tr></thead><tbody>{assignments.map((assignment) => <tr key={assignment.id}><th scope="row"><span className="platform-org-name">{assignment.email}</span><small>User ID: {assignment.user_id}</small></th><td>{roleLabel(assignment.role)}</td><td>{formatDate(assignment.assigned_at)}</td><td><button type="button" className="danger-button tenant-small-action" disabled={assigningRole} onClick={() => void revokeRole(assignment)}>Revoke role</button></td></tr>)}</tbody></table></div>}
      </div>
    </section>}

    {activeTab === "audit" && canReadAudit && <section className="platform-panel" role="tabpanel" aria-label={heading}>
      <div className="platform-panel-heading"><div><p className="eyebrow">GOVERNANCE RECORD</p><h2>Platform audit events</h2><p>Latest 100 events. The API returns a sanitized operational view; document names, query text, answers, chunks and citation text are not available in this feed.</p></div><span className="platform-count">{auditEvents.length} events</span></div>
      {loading && auditEvents.length === 0 ? <p className="platform-empty" role="status">Loading platform audit events…</p> : auditEvents.length === 0 ? <p className="platform-empty">No platform audit events were returned.</p> : <div className="tenant-audit-list">{auditEvents.map((event) => <article className="tenant-audit-item" key={event.id}><div className="tenant-audit-main"><div><strong>{statusLabel(event.event_type)}</strong><small>Event {event.id} · Actor {event.actor_user_id ?? "system"}</small><small>Organisation {event.organisation_id ?? "platform-wide"} · Target {event.target_type ?? "—"}{event.target_id ? ` · ${event.target_id}` : ""}</small></div><time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time></div>{Object.keys(event.details).length > 0 && <dl>{Object.entries(event.details).map(([key, value]) => <div key={key}><dt>{statusLabel(key)}</dt><dd>{String(value)}</dd></div>)}</dl>}</article>)}</div>}
      <p className="tenant-footnote">This is an operational audit view, not a tenant content viewer. Sensitive event payloads are filtered server-side before reaching this page.</p>
    </section>}
  </main>;
}

function Metric({ label, value, loading, attention = false }: { label: string; value: number | undefined; loading: boolean; attention?: boolean }) {
  return <article className={`metric-card${attention ? " metric-card--attention" : ""}`}><div className="metric-topline"><span>{label}</span></div><strong className="metric-value">{loading || typeof value !== "number" ? "—" : value.toLocaleString()}</strong><span className="metric-caption">Aggregate platform metric</span></article>;
}
