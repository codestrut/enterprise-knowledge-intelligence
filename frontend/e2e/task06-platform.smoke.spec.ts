import { expect, test, type Page } from "@playwright/test";

function capturePlatformApiRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) requests.push(request.url());
  });
  return requests;
}

test("platform tenant directory loads synthetic lifecycle states through the loopback proxy", async ({ page }) => {
  const platformApiRequests = capturePlatformApiRequests(page);
  await page.goto("/platform");

  await expect(page.getByRole("heading", { name: "Tenant administration" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Organisations" })).toBeVisible();
  await expect(page.getByText("Synthetic Pending Institute")).toBeVisible();
  await expect(page.getByText("Synthetic Stale Institute")).toBeVisible();
  await expect(page.getByText("Synthetic Failed Institute")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & provision" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Recover stale attempt" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry provisioning" })).toBeVisible();
  await expect(page.getByText("View tenants", { exact: true })).toBeVisible();

  // Browser traffic must stay on Vite's loopback origin. Vite forwards API calls
  // only to the synthetic in-memory mock on port 8003.
  expect(platformApiRequests.length).toBeGreaterThan(0);
  for (const requestUrl of platformApiRequests) {
    const url = new URL(requestUrl);
    expect(url.origin).toBe("http://127.0.0.1:5174");
    expect(url.port).not.toBe("8000");
    expect(url.port).not.toBe("8002");
  }
  expect(platformApiRequests.map((requestUrl) => new URL(requestUrl).pathname)).toEqual(
    expect.arrayContaining([
      "/api/auth/me",
      "/api/health",
      "/api/documents",
      "/api/platform/organisations",
    ]),
  );
});

test("platform operator can create a pending registration, search a user, and assign a role", async ({ page }) => {
  const platformApiRequests = capturePlatformApiRequests(page);
  await page.goto("/platform");
  await expect(page.getByRole("heading", { name: "Tenant administration" })).toBeVisible();

  await page.getByLabel("Organisation name").fill("Northern Research Institute");
  await page.getByLabel("Tenant slug").fill("northern-research");
  await page.getByLabel("Initial administrator email").fill("initial-admin@example.test");
  await page.getByRole("button", { name: "Create registration" }).click();

  await expect(page.getByText("Tenant registration created. It remains inactive until explicitly approved and provisioned.")).toBeVisible();
  const newTenantRow = page.getByRole("row", { name: /Northern Research Institute/ });
  await expect(newTenantRow).toBeVisible();
  await expect(newTenantRow.getByText("registration pending")).toBeVisible();
  await expect(newTenantRow.getByRole("button", { name: "Approve & provision" })).toBeVisible();

  await page.getByLabel("Search users by email").fill("owner");
  await page.getByRole("button", { name: "Search users" }).click();
  await expect(page.getByText("Found 1 user.", { exact: true })).toBeVisible();

  await page.getByRole("region", { name: "Platform role assignment" }).getByLabel("Account").selectOption("44444444-4444-4444-8444-444444444444");
  await page.getByRole("region", { name: "Platform role assignment" }).getByLabel("Platform role").selectOption("platform_tenant_approver");
  await page.getByRole("button", { name: "Assign platform role" }).click();
  await expect(page.getByText("Assigned platform_tenant_approver to owner@example.test.", { exact: true })).toBeVisible();

  expect(platformApiRequests.some((url) => new URL(url).pathname === "/api/platform/users")).toBe(true);
  expect(platformApiRequests.some((url) => new URL(url).pathname === "/api/platform/users/roles")).toBe(true);
});

test("platform operator can approve, recover, and retry without activating tenants", async ({ page }) => {
  const platformApiRequests = capturePlatformApiRequests(page);
  page.on("dialog", async (dialog) => {
    await dialog.accept("Isolated Task 06 browser smoke verification.");
  });
  await page.goto("/platform");
  await expect(page.getByRole("heading", { name: "Tenant administration" })).toBeVisible();

  const pending = page.getByRole("row", { name: /Synthetic Pending Institute/ });
  await pending.getByRole("button", { name: "Approve & provision" }).click();
  await expect(pending.getByText("Awaiting initial admin")).toBeVisible();
  await expect(pending.getByText("pending admin")).toBeVisible();

  const stale = page.getByRole("row", { name: /Synthetic Stale Institute/ });
  await stale.getByRole("button", { name: "Recover stale attempt" }).click();
  await expect(stale.getByText("provisioning failed")).toBeVisible();
  await expect(stale.getByRole("button", { name: "Retry provisioning" })).toBeVisible();

  const failed = page.getByRole("row", { name: /Synthetic Failed Institute/ });
  await failed.getByRole("button", { name: "Retry provisioning" }).click();
  await expect(failed.getByText("Awaiting initial admin")).toBeVisible();
  await expect(failed.getByText("pending admin")).toBeVisible();

  for (const requestUrl of platformApiRequests) {
    const url = new URL(requestUrl);
    expect(url.origin).toBe("http://127.0.0.1:5174");
    expect(url.port).not.toBe("8000");
    expect(url.port).not.toBe("8002");
  }
});
