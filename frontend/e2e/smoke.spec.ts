import { expect, test } from "@playwright/test";

const liveLoginEmail = process.env.EKIP_E2E_LOGIN_EMAIL;
const liveLoginPassword = process.env.EKIP_E2E_LOGIN_PASSWORD;
// Optional isolated account with two or more active organisation memberships (F3 selection flow).
const multiOrganisationEmail = process.env.EKIP_E2E_MULTI_ORG_EMAIL;
const multiOrganisationPassword = process.env.EKIP_E2E_MULTI_ORG_PASSWORD;
// Live credentials are submitted by one E2E case; never persist request bodies in traces.
test.use({ trace: "off" });

function inspectLoginGif(bytes: Buffer) {
  expect(bytes.toString("ascii", 0, 6)).toMatch(/^GIF8[79]a$/);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const width = view.getUint16(6, true);
  const height = view.getUint16(8, true);
  const screenFlags = bytes[10];
  let offset = 13 + (screenFlags & 0x80 ? 3 * 2 ** ((screenFlags & 0x07) + 1) : 0);
  const delays: number[] = [];
  let frameCount = 0;
  while (offset < bytes.length) {
    const marker = bytes[offset];
    if (marker === 0x3b) break;
    if (marker === 0x21) {
      const label = bytes[offset + 1];
      if (label === 0xf9) {
        expect(bytes[offset + 2]).toBe(4);
        delays.push(view.getUint16(offset + 4, true));
        offset += 8;
      } else {
        offset += 2;
        while (offset < bytes.length) {
          const blockSize = bytes[offset++];
          if (blockSize === 0) break;
          offset += blockSize;
        }
      }
    } else if (marker === 0x2c) {
      frameCount += 1;
      const imageFlags = bytes[offset + 9];
      offset += 10 + (imageFlags & 0x80 ? 3 * 2 ** ((imageFlags & 0x07) + 1) : 0);
      offset += 1; // LZW minimum code size
      while (offset < bytes.length) {
        const blockSize = bytes[offset++];
        if (blockSize === 0) break;
        offset += blockSize;
      }
    } else {
      throw new Error(`Unexpected GIF block marker: ${marker}`);
    }
  }
  return { width, height, delays, frameCount, loops: bytes.includes(Buffer.from("NETSCAPE2.0")) };
}

test("protected API returns to the managed sign-in form through the frontend proxy", async ({ page }) => {
  const browserRequests: { url: string; method: string }[] = [];
  page.on("request", (request) => browserRequests.push({ url: request.url(), method: request.method() }));
  const sessionCheckResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/me");

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();
  await expect(page.getByLabel("Work email")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Password" })).toBeVisible();
  const loginImage = page.getByAltText("Researchers studying documents and digital information in a collaborative workspace");
  await expect(loginImage).toBeVisible();
  await expect.poll(() => loginImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  const [gifResponse, posterResponse] = await Promise.all([
    page.request.get("/images/ekip-login-research-rotation.gif"),
    page.request.get("/images/ekip-login-research-rotation-poster.jpg"),
  ]);
  expect(gifResponse.ok()).toBeTruthy();
  expect(posterResponse.ok()).toBeTruthy();
  const gif = inspectLoginGif(await gifResponse.body());
  // Six interpolated 60-frame scenes: 20 push-in frames (~0.625s each, 12.5s) then a 40-frame cross-dissolve (~0.104s each, ~4.2s); 100s loop.
  expect({ width: gif.width, height: gif.height, frameCount: gif.frameCount, loops: gif.loops }).toEqual({ width: 400, height: 500, frameCount: 360, loops: true });
  expect(gif.delays.reduce((total, delay) => total + delay, 0)).toBe(10000);
  for (let scene = 0; scene < 6; scene += 1) {
    const delays = gif.delays.slice(scene * 60, scene * 60 + 60);
    expect(delays.slice(0, 20).every((delay) => delay === 62 || delay === 63)).toBe(true);
    expect(delays.slice(20).every((delay) => delay === 10 || delay === 11)).toBe(true);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect.poll(() => loginImage.evaluate((image: HTMLImageElement) => image.currentSrc ? new URL(image.currentSrc).pathname : "")).toBe("/images/ekip-login-research-rotation-poster.jpg");
  await expect.poll(() => loginImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0);
  expect(await loginImage.evaluate((image: HTMLImageElement) => [image.naturalWidth, image.naturalHeight])).toEqual([960, 1200]);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("Work email")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in securely" })).toBeVisible();

  expect((await sessionCheckResponse).status()).toBe(401);
  const health = await page.request.get("/api/health");
  expect(health.ok()).toBeTruthy();

  const apiRequests = browserRequests.filter(({ url }) => new URL(url).pathname.startsWith("/api/"));
  expect(apiRequests.map(({ url }) => new URL(url).pathname)).toEqual(expect.arrayContaining(["/api/auth/me"]));
  expect(apiRequests.map(({ url }) => new URL(url).pathname)).not.toContain("/api/documents");
  for (const request of apiRequests) {
    const url = new URL(request.url);
    expect(url.port).not.toBe("8000");
    expect(url.origin).toBe("http://127.0.0.1:4173");
    expect(request.method).toBe("GET");
  }
});

test("login artwork sits in a subtle tonal frame on desktop and gives the form room on tablet and mobile", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  const visual = page.locator(".login-visual");
  const card = page.locator(".login-visual-card");
  const image = page.getByAltText("Researchers studying documents and digital information in a collaborative workspace");
  await expect(visual).toBeVisible();
  await expect(card).toBeVisible();
  await expect(image).toBeVisible();
  const geometry = await page.evaluate(() => {
    const panel = document.querySelector(".login-visual")!.getBoundingClientRect();
    const cardRect = document.querySelector(".login-visual-card")!.getBoundingClientRect();
    const image = document.querySelector(".login-visual-picture img")!;
    const cardStyle = getComputedStyle(document.querySelector(".login-visual-card")!);
    const picture = document.querySelector(".login-visual-picture")!;
    const pictureRect = picture.getBoundingClientRect();
    const pictureStyle = getComputedStyle(picture);
    const imageBox = image.getBoundingClientRect();
    const matChannels = (pictureStyle.backgroundImage.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
    const captionRgb = getComputedStyle(document.querySelector(".login-visual-caption p")!).color.match(/\d+/g)!.slice(0, 3).map(Number);
    return {
      panelWidth: panel.width,
      cardWidth: cardRect.width,
      cardFrame: [cardStyle.backgroundColor, cardStyle.backgroundImage, cardStyle.paddingLeft, cardStyle.borderTopWidth, cardStyle.boxShadow],
      matPadding: Number.parseFloat(pictureStyle.paddingLeft),
      matBorderWidth: pictureStyle.borderTopWidth,
      matGradient: pictureStyle.backgroundImage.startsWith("linear-gradient"),
      matMaxChannel: Math.max(...matChannels.slice(1, 4), ...matChannels.slice(5, 8)),
      matInsets: [imageBox.left - pictureRect.left, pictureRect.right - imageBox.right, imageBox.top - pictureRect.top, pictureRect.bottom - imageBox.bottom].map((inset) => Math.round(inset)),
      pictureMask: pictureStyle.maskImage || pictureStyle.webkitMaskImage,
      gutterDifference: Math.abs((pictureRect.left - panel.left) - (panel.right - pictureRect.right)),
      captionLightness: captionRgb.reduce((total, channel) => total + channel, 0) / 3,
      imageRatio: imageBox.width / imageBox.height,
      objectFit: getComputedStyle(image).objectFit,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
  expect(geometry.cardWidth).toBeLessThan(geometry.panelWidth * 0.9);
  // No pale card around artwork and caption; the artwork alone sits in a thin, dark tonal mat with even insets.
  expect(geometry.cardFrame).toEqual(["rgba(0, 0, 0, 0)", "none", "0px", "0px", "none"]);
  expect(geometry.matPadding).toBeGreaterThanOrEqual(4);
  expect(geometry.matPadding).toBeLessThanOrEqual(10);
  expect(geometry.matBorderWidth).toBe("1px");
  expect(geometry.matGradient).toBe(true);
  expect(geometry.matMaxChannel).toBeLessThan(80);
  expect(new Set(geometry.matInsets).size).toBe(1);
  expect(geometry.pictureMask).toBe("none");
  expect(geometry.gutterDifference).toBeLessThanOrEqual(1);
  expect(geometry.captionLightness).toBeGreaterThan(180);
  expect(geometry.imageRatio).toBeCloseTo(0.8, 1);
  expect(geometry.objectFit).toBe("contain");
  expect(geometry.horizontalOverflow).toBe(false);

  for (const width of [820, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(visual).toBeHidden();
    await expect(page.getByLabel("Work email")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign in securely" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test("managed login loads the live profile and logout revokes protected access", async ({ page }) => {
  test.skip(!liveLoginEmail || !liveLoginPassword, "Set isolated test-account credentials in the Playwright process environment.");
  const browserRequests: string[] = [];
  page.on("request", (request) => browserRequests.push(request.url()));

  const unauthenticatedSessionCheck = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/me" && response.request().method() === "GET");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();
  expect((await unauthenticatedSessionCheck).status()).toBe(401);
  const loginResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/login");
  const profileResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/me");
  const protectedDocumentsPromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/documents" && response.request().method() === "GET");
  await page.getByLabel("Work email").fill(liveLoginEmail!);
  await page.getByRole("textbox", { name: "Password" }).fill(liveLoginPassword!);
  await page.getByRole("button", { name: "Sign in securely" }).click();

  const [loginResponse, profileResponse, documentsResponse] = await Promise.all([
    loginResponsePromise,
    profileResponsePromise,
    protectedDocumentsPromise,
  ]);
  expect(loginResponse.status()).toBe(200);
  expect(profileResponse.status()).toBe(200);
  expect(documentsResponse.status()).toBe(200);
  const loginPayload = await loginResponse.json() as { access_token?: string; requires_organisation_selection?: boolean };
  // Precondition: EKIP_E2E_LOGIN_EMAIL is a single-organisation account (selection is covered below).
  expect(loginPayload.requires_organisation_selection).not.toBe(true);
  expect(typeof loginPayload.access_token).toBe("string");
  const auditResponse = await page.request.get("/api/audit/events", {
    headers: { Authorization: `Bearer ${loginPayload.access_token}` },
  });
  expect(auditResponse.status()).toBe(200);
  const profile = await profileResponse.json() as { email: string; role: string; organisation: { name: string } };
  const accountMenu = page.locator(".account-menu");
  await expect(accountMenu).toContainText(profile.email);
  await expect(accountMenu).toContainText(profile.organisation.name);
  await expect(accountMenu).toContainText(profile.role.replaceAll("_", " "));
  await page.locator(".account-menu summary").click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  const logoutResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/logout");
  await page.getByRole("button", { name: "Sign out" }).click();
  const logoutResponse = await logoutResponsePromise;
  expect(logoutResponse.status()).toBe(204);
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();

  const staleTokenResponse = await page.request.get("/api/documents", {
    headers: { Authorization: `Bearer ${loginPayload.access_token}` },
  });
  expect(staleTokenResponse.status()).toBe(401);
  expect(browserRequests.some((url) => new URL(url).port === "8000")).toBe(false);
});

test("multi-organisation login chooses an organisation without retyping the password", async ({ page }) => {
  test.skip(!multiOrganisationEmail || !multiOrganisationPassword, "Set isolated multi-organisation test-account credentials in the Playwright process environment.");
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();

  const selectionResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/login");
  await page.getByLabel("Work email").fill(multiOrganisationEmail!);
  await page.getByRole("textbox", { name: "Password" }).fill(multiOrganisationPassword!);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  const selectionResponse = await selectionResponsePromise;
  expect(selectionResponse.status()).toBe(200);
  const selection = await selectionResponse.json() as { requires_organisation_selection?: boolean; organisations?: { id: string; name: string }[] };
  expect(selection.requires_organisation_selection).toBe(true);
  expect(selection.organisations?.length ?? 0).toBeGreaterThan(1);
  await expect(page.getByRole("status")).toContainText("Choose an organisation to continue.");
  await expect(page.getByRole("textbox", { name: "Password" })).toHaveValue(multiOrganisationPassword!);

  const chosen = selection.organisations![1];
  await page.getByLabel("Organisation").selectOption(chosen.id);
  const tokenResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/login");
  const profileResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/me" && response.status() === 200);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  const tokenResponse = await tokenResponsePromise;
  expect(tokenResponse.status()).toBe(200);
  // Parsed in memory only; the request body contains the password and is never printed.
  expect((JSON.parse(tokenResponse.request().postData() ?? "{}") as { organisation_id?: string }).organisation_id).toBe(chosen.id);
  const profile = await (await profileResponsePromise).json() as { organisation: { id: string; name: string } };
  expect(profile.organisation.id).toBe(chosen.id);
  await expect(page.locator(".account-menu")).toContainText(chosen.name);

  await page.locator(".account-menu summary").click();
  const logoutResponsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/auth/logout");
  await page.getByRole("button", { name: "Sign out" }).click();
  expect((await logoutResponsePromise).status()).toBe(204);
  await expect(page.getByRole("heading", { name: "Turn information into clarity." })).toBeVisible();
});
