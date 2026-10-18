import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiRequestError, getCurrentUser, login, logout, setAccessToken, type OrganisationChoice } from "./api/client";
import type { CurrentUserProfile } from "./api/types";

// "unknown" lasts until the initial session check settles; nothing protected renders before then.
// Tokens are memory-only today, so the check normally ends signed out; Task 05.4 can restore a
// cookie-backed session through the same state.
export type AuthStatus = "unknown" | "signedIn" | "signedOut";
export type SignInResult = "signedIn" | "needsOrganisation" | "noOrganisation";
export const INITIAL_AUTH_UNAVAILABLE = "We couldn't confirm your sign-in status. Sign in to continue.";

interface AuthValue {
  status: AuthStatus;
  loginRequired: boolean;
  loading: boolean;
  profile: CurrentUserProfile | null;
  permissions: ReadonlySet<string> | null;
  organisationChoices: OrganisationChoice[];
  message: string;
  signIn: (email: string, password: string, organisationId?: string) => Promise<SignInResult>;
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
  clearChoices: () => void;
  clearMessage: () => void;
}

const AuthContext = createContext<AuthValue>({
  status: "unknown",
  loginRequired: false,
  loading: false,
  profile: null,
  permissions: null,
  organisationChoices: [],
  message: "",
  signIn: async () => "signedIn",
  refreshProfile: async () => undefined,
  signOut: async () => undefined,
  clearChoices: () => undefined,
  clearMessage: () => undefined,
});

type InitialAuthResult = { kind: "signedIn"; profile: CurrentUserProfile } | { kind: "signedOut" } | { kind: "unavailable" } | { kind: "aborted" };
type InitialAuthRequest = { controller: AbortController; promise: Promise<InitialAuthResult>; subscribers: number; settled: boolean };
let initialAuthRequest: InitialAuthRequest | null = null;

async function resolveInitialAuth(signal: AbortSignal): Promise<InitialAuthResult> {
  try {
    return { kind: "signedIn", profile: await getCurrentUser(signal) };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return { kind: "aborted" };
    if (error instanceof ApiRequestError && error.status === 401) return { kind: "signedOut" };
    return { kind: "unavailable" };
  }
}

// Shared so React StrictMode's effect replay does not issue a second session check.
function subscribeToInitialAuth() {
  if (!initialAuthRequest) {
    const controller = new AbortController();
    const request: InitialAuthRequest = { controller, promise: resolveInitialAuth(controller.signal), subscribers: 0, settled: false };
    initialAuthRequest = request;
    void request.promise.then(() => {
      request.settled = true;
      if (request.subscribers === 0 && initialAuthRequest === request) initialAuthRequest = null;
    });
  }
  const request = initialAuthRequest;
  request.subscribers += 1;
  let released = false;
  return {
    promise: request.promise,
    release() {
      if (released) return;
      released = true;
      request.subscribers -= 1;
      queueMicrotask(() => {
        if (request.subscribers !== 0 || initialAuthRequest !== request) return;
        if (!request.settled) request.controller.abort();
        initialAuthRequest = null;
      });
    },
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("unknown");
  const statusRef = useRef<AuthStatus>("unknown");
  const [loading, setLoading] = useState(false);
  const [profile, setProfile] = useState<CurrentUserProfile | null>(null);
  const [permissions, setPermissions] = useState<ReadonlySet<string> | null>(null);
  const [organisationChoices, setOrganisationChoices] = useState<OrganisationChoice[]>([]);
  const [message, setMessage] = useState("");

  function updateStatus(next: AuthStatus) {
    statusRef.current = next;
    setStatus(next);
  }

  function clearSession() {
    setAccessToken(null);
    setProfile(null);
    setPermissions(null);
    updateStatus("signedOut");
  }

  useEffect(() => {
    let active = true;
    const request = subscribeToInitialAuth();
    void request.promise.then((result) => {
      // A sign-in, sign-out or expiry that already happened takes precedence over this check.
      if (!active || result.kind === "aborted" || statusRef.current !== "unknown") return;
      if (result.kind === "signedIn") {
        setProfile(result.profile);
        setPermissions(new Set(result.profile.permissions));
        updateStatus("signedIn");
        return;
      }
      updateStatus("signedOut");
      if (result.kind === "unavailable") setMessage(INITIAL_AUTH_UNAVAILABLE);
    });
    return () => { active = false; request.release(); };
  }, []);

  useEffect(() => {
    const requireLogin = () => {
      const hadAuthenticatedProfile = profile !== null;
      clearSession();
      setOrganisationChoices([]);
      setMessage(hadAuthenticatedProfile ? "Your session expired. Sign in again to continue." : "");
    };
    window.addEventListener("ekip:auth-required", requireLogin);
    return () => window.removeEventListener("ekip:auth-required", requireLogin);
  }, [profile]);

  async function refreshProfile() {
    const current = await getCurrentUser();
    setProfile(current);
    setPermissions(new Set(current.permissions));
    updateStatus("signedIn");
  }

  async function signIn(email: string, password: string, organisationId?: string): Promise<SignInResult> {
    setLoading(true);
    setMessage("");
    try {
      const result = await login(email, password, organisationId);
      if (result && "requires_organisation_selection" in result) {
        setOrganisationChoices(result.organisations);
        return result.organisations.length > 0 ? "needsOrganisation" : "noOrganisation";
      }
      setOrganisationChoices([]);
      await refreshProfile();
      window.dispatchEvent(new CustomEvent("ekip:auth-signed-in"));
      return "signedIn";
    } catch (error) {
      clearSession();
      throw error;
    } finally {
      setLoading(false);
    }
  }

  async function signOut() {
    setLoading(true);
    setMessage("");
    let revoked = true;
    try {
      await logout();
    } catch {
      revoked = false;
    } finally {
      clearSession();
      setOrganisationChoices([]);
      setLoading(false);
      window.dispatchEvent(new CustomEvent("ekip:auth-signed-out"));
      if (!revoked) setMessage("Signed out on this device, but the server could not confirm session revocation.");
    }
  }

  const value = useMemo(() => ({
    status, loginRequired: status === "signedOut", loading, profile, permissions, organisationChoices, message,
    signIn, refreshProfile, signOut,
    clearChoices: () => setOrganisationChoices([]),
    clearMessage: () => setMessage(""),
  }), [status, loading, profile, permissions, organisationChoices, message]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() { return useContext(AuthContext); }
