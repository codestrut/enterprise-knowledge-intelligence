import type { ReactNode } from "react";
import type { HealthResponse } from "./api/types";
import { Icon, type IconName } from "./Icons";
import { handleInternalLink } from "./routing";
import { useAuth } from "./AuthContext";

const links: { href: string; label: string; icon: IconName; id: string }[] = [
  { href: "/", label: "Overview", icon: "overview", id: "overview" },
  { href: "/library", label: "Document library", icon: "library", id: "library" },
  { href: "/workspace", label: "Workspace", icon: "workspace", id: "workspace" },
];

export function AppLink({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return <a href={href} onClick={(event) => handleInternalLink(event, href)} {...props}>{children}</a>;
}

export function formatRoleBadge(role: string): string {
  if (role === "organisation_administrator") return "Admin";
  if (role === "contributor") return "Contributor";
  if (role === "reader") return "Reader";
  return role.replaceAll("_", " ");
}

const PLATFORM_ROLE_LABELS: Record<string, string> = {
  platform_super_administrator: "Super administrator",
  platform_tenant_creator: "Tenant creator",
  platform_tenant_approver: "Tenant approver",
  platform_provisioning_operator: "Provisioning operator",
};

export function formatPlatformRoleBadge(roles: readonly string[]): string {
  if (roles.length === 0) return "Platform operator";
  return roles
    .map((role) => PLATFORM_ROLE_LABELS[role] ?? role.replaceAll("_", " "))
    .join(" · ");
}

export default function AppShell({ children, active, health }: { children: ReactNode; active: string; health: HealthResponse | null }) {
  const auth = useAuth();
  const apiConnected = health !== null;
  const platformPermissions = auth.profile?.platform_permissions ?? [];
  const canReadPlatform = platformPermissions.includes("organisations:read");
  const canReadTenantAdmin = auth.profile?.organisation !== null && auth.profile?.permissions.includes("tenant:read") === true;
  const isPlatformSession = auth.profile?.organisation === null;
  const accountRoleLabel = auth.profile
    ? isPlatformSession
      ? formatPlatformRoleBadge(auth.profile.platform_roles ?? [])
      : formatRoleBadge(auth.profile.role)
    : "";
  const accountRoleKey = auth.profile
    ? isPlatformSession
      ? auth.profile.platform_roles?.[0] ?? "platform_operator"
      : auth.profile.role
    : "";
  const visibleLinks = [
    ...(auth.profile?.organisation ? links : []),
    ...(canReadTenantAdmin ? [{ href: "/tenant/settings", label: "Organisation", icon: "settings" as IconName, id: "tenant-admin" }] : []),
    ...(canReadPlatform ? [{ href: "/platform", label: "Platform admin", icon: "settings" as IconName, id: "platform" }] : []),
  ];
  return <div className="app-shell">
    <header className="topbar">
      <AppLink className="brand" href="/" aria-label="EKIP System Overview"><span className="brand-mark" aria-hidden="true"><span/><span/><span/><span/></span><span className="brand-name">EKIP</span><span className="brand-divider" aria-hidden="true"/><span className="brand-caption">Knowledge intelligence</span></AppLink>
      <nav aria-label="Main navigation" className="main-nav">{visibleLinks.map((link) => <AppLink key={link.id} href={link.href} aria-current={active === link.id ? "page" : undefined}><Icon name={link.icon}/><span>{link.label}</span></AppLink>)}</nav>
      <span className={`api-state ${apiConnected ? "api-state--connected" : "api-state--unknown"}`} role="status"><span className="status-dot" aria-hidden="true"/>{apiConnected ? health.status === "ok" ? "API connected" : `API reachable · ${health.status || "status unknown"}` : "API status unavailable"}</span>
      {auth.profile && <details className="account-menu"><summary aria-label={`Account for ${auth.profile.email}`}><span className="account-avatar" aria-hidden="true">{auth.profile.email.slice(0, 1).toUpperCase()}</span><span className="account-summary"><strong>{auth.profile.email}</strong><small>{auth.profile.organisation?.name ?? "Platform operator"} <span className="role-badge" data-role={accountRoleKey}>{accountRoleLabel}</span></small></span><span aria-hidden="true">⌄</span></summary><div className="account-popover"><p><strong>{auth.profile.email}</strong><span>{auth.profile.organisation?.name ?? "Platform operator"}</span><small>{accountRoleLabel} <span className="role-badge" data-role={accountRoleKey}>{accountRoleLabel}</span></small></p><button type="button" onClick={() => void auth.signOut()} disabled={auth.loading}>Sign out</button></div></details>}
    </header>
    <div className="page-container">{children}</div>
    <footer className="footer"><span>EKIP <span aria-hidden="true">·</span> Enterprise Knowledge Intelligence Platform</span>{auth.profile?.organisation && <AppLink href="/workspace">Open knowledge workspace</AppLink>}</footer>
  </div>;
}
