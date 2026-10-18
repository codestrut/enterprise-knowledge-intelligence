import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getDocuments, getHealth } from "./api/client";
import { useAuth } from "./AuthContext";
import type { DocumentRecord, HealthResponse } from "./api/types";

export type KnowledgeBaseStatus = "loading" | "available" | "unavailable";
export interface KnowledgeBaseValue {
  health: HealthResponse | null;
  documents: DocumentRecord[];
  status: KnowledgeBaseStatus;
  lastUpdated: Date | null;
  refreshing: boolean;
  healthError: string | null;
  documentsError: string | null;
  refresh: () => Promise<{ documents: DocumentRecord[]; documentsError: string | null }>;
}

const emptyValue: KnowledgeBaseValue = { health: null, documents: [], status: "loading", lastUpdated: null, refreshing: false, healthError: null, documentsError: null, refresh: async () => ({ documents: [], documentsError: null }) };
const KnowledgeBaseContext = createContext<KnowledgeBaseValue>(emptyValue);

type StatusResults = [PromiseSettledResult<HealthResponse>, PromiseSettledResult<Awaited<ReturnType<typeof getDocuments>>>];
type SharedStatusRequest = { controller: AbortController; promise: Promise<StatusResults>; subscribers: number; settled: boolean };
let sharedStatusRequest: SharedStatusRequest | null = null;

function subscribeToInitialStatus() {
  if (!sharedStatusRequest) {
    const controller = new AbortController();
    const request: SharedStatusRequest = { controller, promise: Promise.allSettled([getHealth(controller.signal), getDocuments(controller.signal)]) as Promise<StatusResults>, subscribers: 0, settled: false };
    sharedStatusRequest = request;
    void request.promise.then(() => {
      request.settled = true;
      if (request.subscribers === 0 && sharedStatusRequest === request) sharedStatusRequest = null;
    });
  }
  const request = sharedStatusRequest;
  request.subscribers += 1;
  let released = false;
  return {
    promise: request.promise,
    release() {
      if (released) return;
      released = true;
      request.subscribers -= 1;
      queueMicrotask(() => {
        if (request.subscribers !== 0 || sharedStatusRequest !== request) return;
        if (!request.settled) request.controller.abort();
        sharedStatusRequest = null;
      });
    },
  };
}

export function KnowledgeBaseProvider({ children }: { children: ReactNode }) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [status, setStatus] = useState<KnowledgeBaseStatus>("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const latest = useRef({ documents, documentsError });
  latest.current = { documents, documentsError };
  const { status: authStatus } = useAuth();
  // Bumped whenever the signed-in session ends so results from an earlier session are dropped.
  const sessionGeneration = useRef(0);

  const clearSessionState = useCallback(() => {
    sessionGeneration.current += 1;
    latest.current = { documents: [], documentsError: null };
    setHealth(null); setDocuments([]); setStatus("loading"); setLastUpdated(null);
    setRefreshing(false); setHealthError(null); setDocumentsError(null);
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal): Promise<{ documents: DocumentRecord[]; documentsError: string | null }> => {
      const generation = sessionGeneration.current;
      setRefreshing(true);
      const [healthResult, documentsResult] = await Promise.allSettled([getHealth(signal), getDocuments(signal)]);
      if (signal?.aborted || generation !== sessionGeneration.current) return latest.current;
      let nextDocuments = latest.current.documents;
      let nextDocumentsError = latest.current.documentsError;
      if (healthResult.status === "fulfilled") { setHealth(healthResult.value); setHealthError(null); }
      else setHealthError(healthResult.reason instanceof Error ? healthResult.reason.message : "Could not load API health.");
      if (documentsResult.status === "fulfilled") { nextDocuments = documentsResult.value.documents; nextDocumentsError = null; setDocuments(nextDocuments); setDocumentsError(null); }
      else { nextDocumentsError = documentsResult.reason instanceof Error ? documentsResult.reason.message : "Could not load documents."; setDocumentsError(nextDocumentsError); }
      const hasData = healthResult.status === "fulfilled" || documentsResult.status === "fulfilled";
      setStatus(hasData && healthResult.status === "fulfilled" && documentsResult.status === "fulfilled" ? "available" : "unavailable");
      if (hasData) setLastUpdated(new Date());
      setRefreshing(false);
      return { documents: nextDocuments, documentsError: nextDocumentsError };
  }, []);

  useEffect(() => {
    // Session-scoped state exists only while signed in; sign-out, expiry or an unknown session
    // clears it and abandons any in-flight status request.
    if (authStatus !== "signedIn") { clearSessionState(); return; }
    let mounted = true;
    const generation = sessionGeneration.current;
    const request = subscribeToInitialStatus();
    setRefreshing(true);
    void request.promise.then(([healthResult, documentsResult]) => {
      if (!mounted || generation !== sessionGeneration.current) return;
      if (healthResult.status === "fulfilled") { setHealth(healthResult.value); setHealthError(null); }
      else setHealthError(healthResult.reason instanceof Error ? healthResult.reason.message : "Could not load API health.");
      if (documentsResult.status === "fulfilled") { setDocuments(documentsResult.value.documents); setDocumentsError(null); }
      else setDocumentsError(documentsResult.reason instanceof Error ? documentsResult.reason.message : "Could not load documents.");
      const hasData = healthResult.status === "fulfilled" || documentsResult.status === "fulfilled";
      setStatus(hasData && healthResult.status === "fulfilled" && documentsResult.status === "fulfilled" ? "available" : "unavailable");
      if (hasData) setLastUpdated(new Date());
      setRefreshing(false);
    });
    return () => { mounted = false; request.release(); };
  }, [authStatus, clearSessionState]);

  const value = useMemo(() => ({ health, documents, status, lastUpdated, refreshing, healthError, documentsError, refresh: () => refresh() }), [health, documents, status, lastUpdated, refreshing, healthError, documentsError, refresh]);
  return <KnowledgeBaseContext.Provider value={value}>{children}</KnowledgeBaseContext.Provider>;
}

export function useKnowledgeBase() { return useContext(KnowledgeBaseContext); }
