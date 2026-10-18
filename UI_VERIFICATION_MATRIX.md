# UI Verification Matrix

Evidence is from the Playwright browser run against the isolated test API on `127.0.0.1:8001`, except where marked as source/config or unit-test evidence. “PASS” means the named path was actually exercised; it does not imply production verification.

| Screen or behavior | Result | Evidence |
|---|---|---|
| Login screen, clean initial load | PASS | Real Chromium page rendered title and login form; no false expired-session alert; 390×844 viewport had no horizontal overflow. |
| Invalid login | PASS | Browser submitted an incorrect password; login endpoint returned 401 and the UI showed the authentication error. |
| Login and identity/profile | PASS | Synthetic account login returned 200; `/auth/me` returned 200; account menu showed identity, organisation and role. Credentials were not emitted. |
| Dashboard | PASS | “Knowledge operations” and API-connected status rendered after login. |
| Navigation and keyboard use | PASS | Focus + Enter navigated to Library; login submitted with Enter; account/logout used keyboard; delete dialog dismissed with Escape. |
| Library empty state | PASS | Empty list rendered before upload; after UI deletion the empty state returned. |
| Upload and indexing | PASS | In-memory synthetic PDF uploaded through browser; 201 response; indexing confirmed and filename listed. |
| Query/workspace loading | PASS | Workspace showed scope count and accepted query; submission completed through live isolated API. |
| Grounded answer and citations | PASS | Unique synthetic fact returned with `refused=false`, sufficient evidence, answer containing the fact, and a citation matching `source_map[n]`, `sources[n-1]`, and available source/page/chunk metadata. Claim verification displayed the evidence passage; citation navigation highlighted its source. |
| Insufficient-evidence response | PASS | An absent fact query returned refusal or insufficient evidence; refusal UI displayed. |
| Loading/error/retry | PASS | Playwright held the library request to observe “Refreshing”, fulfilled it with a synthetic 503, asserted error UI, then retried successfully. 503 was browser-injected, not an API outage. |
| Delete confirmation and deletion | PASS | Dialog shown, Escape dismissed it; confirmed deletion returned 200 with `file_deleted=true`, `cleanup_required=false`; UI returned to empty list. |
| Logout and revoked session | PASS | Logout returned 204 and login screen rendered; reuse of the pre-logout access token against protected documents returned 401. |
| Expired-session behavior | NOT TESTED (manual) | No wait for real token expiry or browser token-expiry simulation. Unit regression distinguishes initial unauthenticated 401 from a previously authenticated session becoming invalid. |
| Responsive authenticated screens | NOT TESTED | Desktop authenticated app checked at 1365×900. Only the login screen received the narrow 390×844 overflow assertion. |
| Console and network | PASS | 3 expected HTTP-status console messages (auth 401 / injected 503), 0 uncaught page errors, 0 failed requests; browser requests remained on `127.0.0.1:4173` and its frontend proxy. |
| Production isolation | PASS | No HTTP request to port 8000; Vite rejects that proxy target. Production container was only observed via container listing, not contacted or modified. |
