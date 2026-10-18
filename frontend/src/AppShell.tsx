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

export default function AppShell({ children, active, health }: { children: ReactNode; active: string; health: HealthResponse | null }) {
  const auth = useAuth();
  const apiConnected = health !== null;
  return <div className="app-shell">
    <header className="topbar">
      <AppLink className="brand" href="/" aria-label="EKIP System Overview"><span className="brand-mark" aria-hidden="true"><span/><span/><span/><span/></span><span className="brand-name">EKIP</span><span className="brand-divider" aria-hidden="true"/><span className="brand-caption">Knowledge intelligence</span></AppLink>
      <nav aria-label="Main navigation" className="main-nav">{links.map((link) => <AppLink key={link.id} href={link.href} aria-current={active === link.id ? "page" : undefined}><Icon name={link.icon}/><span>{link.label}</span></AppLink>)}</nav>
      <span className={`api-state ${apiConnected ? "api-state--connected" : "api-state--unknown"}`} role="status"><span className="status-dot" aria-hidden="true"/>{apiConnected ? health.status === "ok" ? "API connected" : `API reachable · ${health.status || "status unknown"}` : "API status unavailable"}</span>
      {auth.profile && <details className="account-menu"><summary aria-label={`Account for ${auth.profile.email}`}><span className="account-avatar" aria-hidden="true">{auth.profile.email.slice(0, 1).toUpperCase()}</span><span className="account-summary"><strong>{auth.profile.email}</strong><small>{auth.profile.organisation.name}</small></span><span aria-hidden="true">⌄</span></summary><div className="account-popover"><p><strong>{auth.profile.email}</strong><span>{auth.profile.organisation.name}</span><small>{auth.profile.role.replaceAll("_", " ")}</small></p><button type="button" onClick={() => void auth.signOut()} disabled={auth.loading}>Sign out</button></div></details>}
    </header>
    <div className="page-container">{children}</div>
    <footer className="footer"><span>EKIP <span aria-hidden="true">·</span> Enterprise Knowledge Intelligence Platform</span><AppLink href="/workspace">Open knowledge workspace</AppLink></footer>
  </div>;
}
