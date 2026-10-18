import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

const email = process.env.EKIP_E2E_LOGIN_EMAIL;
const password = process.env.EKIP_E2E_LOGIN_PASSWORD;

// This test submits credentials and a runtime-only synthetic PDF. Keep trace data off.
test.use({ trace: "off" });

function syntheticPdf(recordCode: string): Buffer {
  const content = `BT /F1 16 Tf 72 720 Td (Record ${recordCode}: the synthetic review marker color is cobalt.) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${Buffer.byteLength(content, "ascii")} >>\nstream\n${content}\nendstream`,
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf, "ascii"));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf, "ascii");
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets.slice(1)) pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf, "ascii");
}

test("manual isolated UI flow: auth, library, grounded query, refusal, errors, deletion and logout", async ({ page }) => {
  test.skip(!email || !password, "Set isolated synthetic-account credentials in the Playwright process environment.");
  test.setTimeout(240_000);

  const pageErrors: string[] = [];
  const failedRequests: string[] = [];
  const consoleErrors: string[] = [];
  const apiResponses: { path: string; status: number }[] = [];
  const browserUrls: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("requestfailed", (request) => failedRequests.push(new URL(request.url()).pathname));
  page.on("request", (request) => browserUrls.push(request.url()));
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) apiResponses.push({ path: url.pathname, status: response.status() });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();
  await expect(page.getByLabel("Work email")).toBeVisible();
  const passwordInput = page.getByRole("textbox", { name: "Password" });
  await expect(passwordInput).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  const badLogin = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/login");
  await page.getByLabel("Work email").fill(email!);
  await passwordInput.fill(`incorrect-${randomUUID()}`);
  await passwordInput.press("Enter");
  expect((await badLogin).status()).toBe(401);
  await expect(page.getByRole("alert")).toContainText("Authentication failed");

  const loginResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/login");
  const profileResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/me");
  await passwordInput.fill(password!);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  const [loginResponse, profileResponse] = await Promise.all([loginResponsePromise, profileResponsePromise]);
  expect(loginResponse.status()).toBe(200);
  expect(profileResponse.status()).toBe(200);
  const loginPayload = await loginResponse.json() as { access_token: string };
  const profile = await profileResponse.json() as { email: string; organisation: { name: string }; role: string };
  await expect(page.getByRole("heading", { name: "Knowledge operations" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "API connected" })).toBeVisible();
  const accountMenu = page.locator(".account-menu");
  await expect(accountMenu).toContainText(profile.email);
  await expect(accountMenu).toContainText(profile.organisation.name);
  await expect(accountMenu).toContainText(profile.role.replaceAll("_", " "));
  await page.setViewportSize({ width: 1365, height: 900 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();

  const libraryLink = page.getByRole("link", { name: "Document library" });
  await libraryLink.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByText("No documents indexed")).toBeVisible();

  const recordCode = `UI${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const fileName = `synthetic-ui-${recordCode}.pdf`;
  await page.getByLabel(/Choose PDF file/).setInputFiles({
    name: fileName,
    mimeType: "application/pdf",
    buffer: syntheticPdf(recordCode),
  });
  const uploadResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/documents" && response.request().method() === "POST");
  await page.getByRole("button", { name: "Upload and index" }).click();
  const uploadResponse = await uploadResponsePromise;
  expect(uploadResponse.status()).toBe(201);
  await expect(page.getByText("Indexing confirmed.")).toBeVisible({ timeout: 120_000 });
  await expect(page.locator("tbody").getByText(fileName, { exact: true })).toBeVisible();

  await page.getByRole("link", { name: /Ask about this document/ }).click();
  await expect(page.getByRole("heading", { name: "Ask your knowledge base" })).toBeVisible();
  await expect(page.getByText("Searching 1 document")).toBeVisible();
  await page.getByLabel("Your question").fill(`What color is the synthetic review marker in record ${recordCode}?`);
  const groundedQueryPromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/query" && response.request().method() === "POST");
  await page.getByRole("button", { name: "Ask EKIP" }).click();
  const groundedResponse = await groundedQueryPromise;
  expect(groundedResponse.status()).toBe(200);
  const grounded = await groundedResponse.json() as {
    answer: string; refused?: boolean; evidence?: { sufficient?: boolean };
    citations?: { source_number: number; source: string; page: string | number; chunk_id: string | number }[];
    source_map?: Record<string, { source: string; page: string | number; chunk_id: string | number }>;
    sources?: { metadata?: { source?: string; page?: string | number; chunk_id?: string | number } }[];
    grounding?: unknown[];
  };
  expect(grounded.refused).toBe(false);
  expect(grounded.evidence?.sufficient).toBe(true);
  expect(grounded.answer.toLowerCase()).toContain("cobalt");
  expect(grounded.citations?.length).toBeGreaterThan(0);
  for (const citation of grounded.citations ?? []) {
    const mapped = grounded.source_map?.[String(citation.source_number)];
    const source = grounded.sources?.[citation.source_number - 1];
    expect(mapped).toBeTruthy();
    expect(source).toBeTruthy();
    expect(mapped?.source).toBe(citation.source);
    expect(mapped?.page).toBe(citation.page);
    expect(mapped?.chunk_id).toBe(citation.chunk_id);
    expect(source?.metadata?.source).toBe(citation.source);
    expect(source?.metadata?.page).toBe(citation.page);
    expect(source?.metadata?.chunk_id).toBe(citation.chunk_id);
  }
  await expect(page.getByRole("heading", { name: "Answer", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Go to Source/ }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Claim verification" })).toBeVisible();
  await expect(page.locator(".grounding-passages blockquote").first()).toContainText(recordCode);
  await page.getByRole("button", { name: /Go to Source/ }).first().click();
  await expect(page.locator(".source-card--highlighted")).toBeVisible();

  await page.getByLabel("Your question").fill(`What is the launch date for unrelated record ${recordCode}?`);
  const refusalResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/query" && response.request().method() === "POST");
  await page.getByRole("button", { name: "Ask EKIP" }).click();
  const refusalResponse = await refusalResponsePromise;
  expect(refusalResponse.status()).toBe(200);
  const refusal = await refusalResponse.json() as { refused?: boolean; evidence?: { sufficient?: boolean } };
  expect(refusal.refused === true || refusal.evidence?.sufficient === false).toBeTruthy();
  await expect(page.getByRole("heading", { name: "A sufficient answer wasn’t available" })).toBeVisible();

  await page.getByRole("link", { name: "Document library" }).click();
  await expect(page.locator("tbody").getByText(fileName, { exact: true })).toBeVisible();
  let releaseDocuments!: () => void;
  let markRequest!: () => void;
  const held = new Promise<void>((resolve) => { releaseDocuments = resolve; });
  const requested = new Promise<void>((resolve) => { markRequest = resolve; });
  await page.route("**/api/documents", async (route) => {
    if (route.request().method() === "GET") {
      markRequest();
      await held;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Synthetic UI verification outage." }) });
      return;
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Refresh library" }).click();
  await requested;
  await expect(page.getByRole("button", { name: "Refreshing" })).toBeVisible();
  releaseDocuments();
  await expect(page.getByRole("alert")).toContainText("Could not load documents");
  await page.unroute("**/api/documents");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator("tbody").getByText(fileName, { exact: true })).toBeVisible();

  await page.locator("tbody").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("dialog", { name: "Delete document?" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.locator("tbody").getByRole("button", { name: "Delete" }).click();
  const deleteResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname.startsWith("/api/documents/") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "Delete document" }).click();
  const deleteResponse = await deleteResponsePromise;
  expect(deleteResponse.status()).toBe(200);
  const deletion = await deleteResponse.json() as { file_deleted: boolean; cleanup_required: boolean };
  expect(deletion.file_deleted).toBe(true);
  expect(deletion.cleanup_required).toBe(false);
  await expect(page.getByText("No documents indexed")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "was deleted from the knowledge base" })).toBeVisible();

  await page.locator(".account-menu summary").focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Sign out" }).focus();
  const logoutResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/logout");
  await page.keyboard.press("Enter");
  expect((await logoutResponsePromise).status()).toBe(204);
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();
  const revoked = await page.request.get("/api/documents", { headers: { Authorization: `Bearer ${loginPayload.access_token}` } });
  expect(revoked.status()).toBe(401);

  expect(pageErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(consoleErrors.filter((message) => !/status of (401|503)/.test(message))).toEqual([]);
  expect(browserUrls.every((url) => new URL(url).origin === "http://127.0.0.1:4173")).toBeTruthy();
  expect(browserUrls.some((url) => new URL(url).port === "8000")).toBe(false);
  expect(apiResponses.some((response) => response.path === "/api/auth/login" && response.status === 401)).toBe(true);
  expect(apiResponses.some((response) => response.path === "/api/query" && response.status === 200)).toBe(true);
  expect(apiResponses.some((response) => response.path === "/api/documents" && response.status === 503)).toBe(true);
  console.log(`Browser console: ${consoleErrors.length} expected HTTP-status message(s) (authentication 401 / simulated outage 503); uncaught page errors: ${pageErrors.length}; failed network requests: ${failedRequests.length}.`);
});
