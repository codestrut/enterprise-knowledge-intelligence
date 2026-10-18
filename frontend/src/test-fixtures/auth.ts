// Test-only helper: answer the initial `GET /api/auth/me` with an authenticated profile and pass
// every other request to the test's own fetch mock (so existing call-count assertions on that
// mock are unaffected). Use only where a test needs an already signed-in session.
export const authenticatedTestProfile = {
  email: "admin@example.test",
  organisation: { id: "org-test", name: "Test Organisation" },
  role: "organisation_administrator",
  permissions: ["documents:read", "documents:upload", "documents:delete", "documents:query"],
};

type FetchImplementation = (input: string, init?: RequestInit) => unknown;

export function withAuthenticatedProfile(fetchImplementation: FetchImplementation, profile: unknown = authenticatedTestProfile) {
  return (input: string, init?: RequestInit) => {
    if (input === "/api/auth/me") {
      return Promise.resolve(new Response(JSON.stringify(profile), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    return fetchImplementation(input, init);
  };
}
