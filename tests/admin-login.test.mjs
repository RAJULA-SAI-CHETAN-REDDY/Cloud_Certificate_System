import assert from "node:assert/strict";
import { mkdir, readFile } from "node:fs/promises";
import { before, after, test } from "node:test";
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { generateKeyPair, exportJWK, SignJWT } from "../frontend/node_modules/jose/dist/webapi/index.js";
import { browserOptions, python, root } from "./browser-runtime.mjs";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const origin = "http://localhost:8000";
const issuer = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_ga4Llp0Ji";
const domain = "https://ccd-admin-707256068320.auth.ap-south-1.amazoncognito.com";
const clientId = "64tedsgkl2e5c7j6o87q2bdflv";
let server;
let browser;
let privateKey;
let publicJwk;

before(async () => {
  await mkdir(root + "tmp", { recursive: true });
  ({ privateKey, publicKey: publicJwk } = await generateKeyPair("RS256"));
  publicJwk = { ...await exportJWK(publicJwk), kid: "test", alg: "RS256", use: "sig" };
  server = spawn(python, ["backend/local_server.py"], { cwd: root, windowsHide: true, stdio: "ignore" });
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(origin + "/admin.html")).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  browser = await chromium.launch(browserOptions);
});

after(async () => {
  await browser?.close();
  if (server && server.exitCode === null) {
    const stopped = new Promise(resolve => server.once("exit", resolve));
    server.kill();
    await stopped;
  }
});

async function loginScenario(t, options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1280, height: 800 } });
  t.after(() => context.close());
  const page = await context.newPage();
  // The user's older preview process may still be listening on 8000. Serve the
  // new allowlisted assets here; Python tests exercise the real server routes.
  for (const [path, type] of [["/index.html", "text/html"], ["/css/navigation.css", "text/css"]]) {
    await page.route(origin + path, route => readFile(root + "frontend" + path).then(body => route.fulfill({ contentType: type, body })));
  }
  if (options.clock) await page.clock.install();
  let auth;
  let exchangeCount = 0;
  if (options.nonAdmin) {
    await page.route("https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/session", route => route.fulfill({
      status: 403, headers: { "Access-Control-Allow-Origin": origin }, json: { error: "Administrator access required." }
    }));
    await page.route("https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/certificates", async route => {
      const request = route.request();
      if (request.method() === "OPTIONS") {
        await route.fulfill({ headers: { "Access-Control-Allow-Origin": origin,
          "Access-Control-Allow-Methods": "POST,OPTIONS", "Access-Control-Allow-Headers": "Authorization,Content-Type" }, body: "" });
        return;
      }
      assert.equal(request.method(), "POST");
      assert.equal(request.postData(), "{}");
      assert.ok(request.headers().authorization?.split(".").length === 3);
      assert.equal(request.headers()["idempotency-key"], undefined);
      assert.equal(request.headers().cookie, undefined);
      if (options.issueNetworkFailure) { await route.abort(); return; }
      await route.fulfill({ status: options.issueStatus || 403,
        headers: { "Access-Control-Allow-Origin": origin }, json: { error: "Denied" } });
    });
  }
  await page.route(domain + "/oauth2/authorize?**", async route => {
    auth = new URL(route.request().url());
    await route.fulfill({ contentType: "text/html", body: "<p>Test identity provider</p>" });
  });
  await page.route(issuer + "/.well-known/jwks.json", route => route.fulfill({ json: { keys: [publicJwk] } }));
  await page.route(domain + "/oauth2/token", async route => {
    exchangeCount++;
    const fields = new URLSearchParams(route.request().postData());
    assert.equal(fields.get("grant_type"), "authorization_code");
    assert.equal(fields.get("redirect_uri"), origin + "/admin.html");
    const challenge = Buffer.from(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(fields.get("code_verifier")))).toString("base64url");
    assert.equal(challenge, auth.searchParams.get("code_challenge"));
    assert.equal(fields.has("client_secret"), false);
    const now = Math.floor(Date.now() / 1000);
    const token = await new SignJWT({
      token_use: "id", email: "administrator@example.test",
      nonce: options.badNonce ? "wrong-nonce" : auth.searchParams.get("nonce"),
      "cognito:groups": options.nonAdmin ? [] : ["admins"]
    }).setProtectedHeader({ alg: "RS256", kid: "test" })
      .setIssuer(options.badIssuer ? issuer + "-wrong" : issuer)
      .setAudience(options.badAudience ? "wrong-client" : clientId)
      .setSubject("test-admin").setIssuedAt(now)
      .setExpirationTime(options.expired ? now - 60 : now + 900).sign(privateKey);
    const idToken = options.badSignature ? token.slice(0, -12) + "AAAAAAAAAAAA" : token;
    await route.fulfill({ json: { access_token: "mock-access-token", id_token: idToken, token_type: "Bearer", expires_in: 900 } });
  });
  await page.goto(origin + "/admin.html");
  await page.locator("#sign-in:not([disabled])").waitFor();
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL(domain + "/oauth2/authorize?**");
  assert.equal(auth.searchParams.get("response_type"), "code");
  assert.equal(auth.searchParams.get("code_challenge_method"), "S256");
  const state = options.badState ? "wrong-state" : auth.searchParams.get("state");
  await page.goto(origin + "/admin.html?code=mock-code&state=" + encodeURIComponent(state));
  await page.waitForFunction(() => document.getElementById("session-title").textContent !== "Connecting");
  assert.equal(new URL(page.url()).search, "");
  return { page, context, exchanges: () => exchangeCount };
}

test("PKCE login, reload, and sign-out", async t => {
  const { page, exchanges } = await loginScenario(t);
  assert.equal(await page.locator("#session-title").textContent(), "Welcome, administrator");
  assert.equal(await page.locator("#session-email").textContent(), "administrator@example.test");
  await page.reload();
  await page.getByRole("heading", { name: "Welcome, administrator" }).waitFor();
  assert.equal(exchanges(), 1);
  await page.route(domain + "/logout?**", route => route.fulfill({ status: 302, headers: { location: origin + "/verify.html" }, body: "" }));
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.waitForURL(origin + "/verify.html");
  await page.goto(origin + "/admin.html");
  await page.getByRole("heading", { name: "Sign in to your account" }).waitFor();
});

for (const option of ["badState", "badNonce", "badSignature", "badIssuer", "badAudience", "expired"]) {
  test("rejects " + option, async t => {
    const { page, exchanges } = await loginScenario(t, { [option]: true });
    assert.equal(await page.locator("#session-title").textContent(), "Sign-in could not be completed");
    if (option === "badState") assert.equal(exchanges(), 0);
    assert.equal(await page.locator("#session-details").isVisible(), false);
  });
}

test("rejects a signed identity without admins membership", async t => {
  const { page } = await loginScenario(t, { nonAdmin: true });
  assert.equal(await page.locator("#session-title").textContent(), "Administrator access required");
  assert.equal(await page.locator("#session-details").isVisible(), false);
  await page.getByText("Administrator access denied by the server. Certificate issuance denied by the server.", { exact: true }).waitFor();
  assert.equal(await page.locator("#check-access").isVisible(), false);
  assert.equal(await page.locator("#issuance-section").isVisible(), false);
});

for (const options of [{ issueStatus: 400 }, { issueNetworkFailure: true }]) {
  test("non-admin issuance probe does not claim denial for " + JSON.stringify(options), async t => {
    const { page } = await loginScenario(t, { nonAdmin: true, ...options });
    await page.waitForFunction(() => document.getElementById("backend-status").textContent.includes("Access remains blocked."));
    assert.equal((await page.locator("#backend-status").textContent()).includes("Certificate issuance denied by the server."), false);
    assert.equal(await page.locator("#issuance-section").isVisible(), false);
  });
}

test("ends the displayed administrator session at expiry", async t => {
  const { page } = await loginScenario(t, { clock: true });
  await page.getByRole("heading", { name: "Welcome, administrator" }).waitFor();
  await page.clock.fastForward(901000);
  await page.getByRole("heading", { name: "Session expired" }).waitFor();
  assert.equal(await page.locator("#session-details").isVisible(), false);
});

test("protected API check sends ID token and handles denial", async t => {
  const { page } = await loginScenario(t);
  let status = 200;
  await page.route("https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/session", async route => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers: {
        "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "GET,OPTIONS",
        "Access-Control-Allow-Headers": "Authorization"
      }, body: "" });
      return;
    }
    const token = route.request().headers().authorization;
    assert.ok(token?.split(".").length === 3);
    assert.equal(route.request().headers().cookie, undefined);
    await route.fulfill({ status, headers: { "Access-Control-Allow-Origin": origin },
      json: status === 200 ? { authorized: true, role: "Administrator", organization_id: "org-1", organization: "Organization 1" } : { error: "Denied" } });
  });
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByText("Administrator access confirmed by the server.", { exact: true }).waitFor();
  status = 403;
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByText("Administrator access was denied.", { exact: true }).waitFor();
  status = 401;
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByRole("heading", { name: "Session expired" }).waitFor();
});

test("mobile and desktop layout and missing callback session", async t => {
  const context = await browser.newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await page.goto(origin + "/admin.html");
    await page.getByRole("heading", { name: "Sign in to your account" }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: root + "tmp/admin-" + viewport.width + ".png", fullPage: true });
  }
  await page.goto(origin + "/admin.html?code=unexpected&state=missing");
  await page.getByRole("heading", { name: "Sign-in could not be completed" }).waitFor();
  assert.equal(new URL(page.url()).search, "");
});

test("issuance retains the same request on failure and renders successful links", async t => {
  const { page } = await loginScenario(t);
  const api = "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin/";
  const cors = { "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST,GET,OPTIONS",
                 "Access-Control-Allow-Headers": "Authorization,Content-Type,Idempotency-Key" };
  await page.route(api + "session", route => route.fulfill({ headers: cors, json: { authorized: true, role: "Administrator", organization_id: "org-1", organization: "Organization 1" } }));
  await page.getByRole("button", { name: "Check access" }).click();
  await page.locator("#issuance-section:not([hidden])").waitFor();
  await page.getByLabel("Recipient", { exact: true }).fill("Example Recipient");
  await page.getByLabel("Course", { exact: true }).fill("Cloud Computing");
  assert.equal(await page.getByLabel("Issuing organization", { exact: true }).inputValue(), "Organization 1");
  assert.equal(await page.getByLabel("Issuing organization", { exact: true }).getAttribute("readonly"), "");
  await page.getByLabel("Expiry date", { exact: true }).fill("2027-10-10");
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: root + "tmp/issuance-" + width + ".png", fullPage: true });
  }
  const submissions = [];
  const id = "CERT-11111111-1111-4111-8111-111111111111";
  await page.route(api + "certificates", async route => {
    if (route.request().method() === "OPTIONS") { await route.fulfill({ headers: cors, body: "" }); return; }
    const request = route.request();
    assert.equal(request.method(), "POST");
    assert.ok(request.headers().authorization.split(".").length === 3);
    submissions.push({ key: request.headers()["idempotency-key"], body: request.postData() });
    await route.fulfill({ status: submissions.length === 1 ? 503 : 201, headers: cors,
      json: submissions.length === 1 ? { error: "Retry" } : { certificate_id: id,
        notification_status: submissions.length === 2 ? "pending" : "published",
        verification_url: origin + "/verify.html?id=" + id,
        download_url: "https://private-bucket.s3.ap-south-1.amazonaws.com/example.pdf?test=1" } });
  });
  await page.getByRole("button", { name: "Issue certificate", exact: true }).click();
  await page.getByText("Issuance could not be confirmed. Retry this submission.", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("Recipient", { exact: true }).isDisabled(), true);
  await page.getByRole("button", { name: "Retry issuance", exact: true }).click();
  await page.getByText("Certificate issued. Email notification pending; retry this submission after one minute. Download is available for five minutes.", { exact: true }).waitFor();
  assert.equal(await page.getByLabel("Recipient", { exact: true }).isDisabled(), true);
  assert.equal(await page.locator("#issued-id").textContent(), id);
  await page.reload();
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Retry issuance", exact: true }).click();
  await page.getByText("Certificate issued. Email notification queued. Download is available for five minutes.", { exact: true }).waitFor();
  assert.deepEqual(submissions[0], submissions[1]);
  assert.deepEqual(submissions[1], submissions[2]);
  assert.equal(await page.getByLabel("Recipient", { exact: true }).isDisabled(), false);
  assert.equal(await page.locator("#issued-id").textContent(), id);
  assert.equal(await page.getByRole("link", { name: "Download PDF", exact: true }).getAttribute("rel"), "noreferrer noopener");
});

test("management pagination, cancel, revoke, email retry and access expiry", async t => {
  const { page } = await loginScenario(t, { viewport: { width: 390, height: 844 } });
  const api = "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin";
  const id = "CERT-12345678-1234-4234-8234-123456789abc";
  let revocations = 0;
  let denied = false;
  await page.route(api + "/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = { "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Authorization" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers, body: "" });
    assert.ok(request.headers().authorization);
    assert.equal(request.headers().cookie, undefined);
    if (url.pathname.endsWith("/session")) return route.fulfill({ headers, json: { authorized: true, role: "Administrator", organization_id: "org-1", organization: "Organization 1" } });
    if (denied) return route.fulfill({ status: 401, headers, json: {} });
    if (url.pathname.endsWith("/revoke")) {
      assert.equal(request.method(), "POST");
      revocations++;
      return route.fulfill({ headers, json: { certificate_id: id, status: "REVOKED", notification_status: revocations === 1 ? "pending" : "published" } });
    }
    return route.fulfill({ headers, json: url.searchParams.has("cursor")
      ? { certificates: [{ certificate_id: id, recipient_name: "<img src=x onerror=alert(1)>", course_name: "Cloud", organization: "Organization 1", can_manage: true, issue_date: "2026-01-01", expiry_date: "2027-01-01", status: "ACTIVE" }], next_cursor: null }
      : { certificates: [], next_cursor: "NOTIFY#event" } });
  });
  assert.equal(await page.locator("#management-section").isVisible(), false);
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Load certificates", exact: true }).click();
  await page.getByRole("button", { name: "Load more", exact: true }).click();
  const revoke = page.getByRole("button", { name: "Revoke certificate", exact: true });
  await revoke.waitFor();
  assert.equal(await page.locator("#certificate-list img").count(), 0);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  page.once("dialog", dialog => dialog.dismiss());
  await revoke.click();
  assert.equal(revocations, 0);
  page.once("dialog", dialog => dialog.accept());
  await revoke.click();
  await page.getByText("Certificate revoked. Email notification pending; retry after one minute.", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Retry revocation email" }).click();
  await page.getByText("Certificate revoked. Email notification queued.", { exact: true }).waitFor();
  assert.equal(revocations, 2);
  await page.screenshot({ path: root + "tmp/admin-management-mobile.png", fullPage: true });
  denied = true;
  await page.getByRole("button", { name: "Load certificates", exact: true }).click();
  await page.getByRole("heading", { name: "Session expired" }).waitFor();
  assert.equal(await page.locator("#management-section").isVisible(), false);
  assert.equal(await page.locator("#certificate-list").textContent(), "");
});

test("home navigation and certificate search, status filters and sorting", async t => {
  const { page } = await loginScenario(t, { viewport: { width: 390, height: 844 } });
  const api = "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin";
  const records = [
    { certificate_id: "CERT-11111111-1111-4111-8111-111111111111", recipient_name: "Zara", course_name: "Cloud", organization: "Organization 1", can_manage: true, issue_date: "2026-01-01", expiry_date: "2027-01-01", status: "ACTIVE" },
    { certificate_id: "CERT-22222222-2222-4222-8222-222222222222", recipient_name: "Amir", course_name: "Networks", organization: "Organization 1", can_manage: true, issue_date: "2026-02-01", expiry_date: "2027-02-01", status: "REVOKED" }
  ];
  await page.route(api + "/**", route => route.fulfill({ headers: { "Access-Control-Allow-Origin": origin }, json: route.request().url().endsWith("/session") ? { authorized: true, role: "Administrator", organization_id: "org-1", organization: "Organization 1" } : { certificates: records, next_cursor: null } }));
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Load certificates", exact: true }).click();
  await page.getByText("All pages loaded.", { exact: true }).waitFor();
  assert.equal(await page.locator("#certificate-list h3").first().textContent(), "Amir");
  await page.locator("#certificate-search").fill("CLOUD");
  assert.equal(await page.locator("#certificate-list h3").textContent(), "Zara");
  await page.locator("#certificate-search").fill("missing");
  assert.equal(await page.locator("#no-matches").isVisible(), true);
  await page.locator("#certificate-search").fill("");
  assert.deepEqual(await page.locator("#certificate-status option").evaluateAll(options => options.map(option => [option.value, option.textContent])), [
    ["", "All statuses"], ["ACTIVE", "Active"], ["EXPIRED", "Expired"], ["REVOKED", "Revoked"], ["NOT_YET_VALID", "Not yet valid"]
  ]);
  await page.locator("#certificate-status").selectOption("ACTIVE");
  assert.equal(await page.locator("#certificate-list h3").textContent(), "Zara");
  await page.locator("#certificate-status").selectOption("REVOKED");
  assert.equal(await page.locator("#certificate-list h3").textContent(), "Amir");
  await page.locator("#certificate-status").selectOption("");
  await page.locator("#certificate-sort").selectOption("oldest");
  assert.equal(await page.locator("#certificate-list h3").first().textContent(), "Zara");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: root + "tmp/admin-search-mobile.png", fullPage: true });
  await page.getByRole("link", { name: "Home", exact: true }).click();
  await page.getByRole("heading", { name: "What would you like to do?" }).waitFor();
  await page.screenshot({ path: root + "tmp/home-mobile.png", fullPage: true });
  await page.locator("main").getByRole("link", { name: "Public verification" }).click();
  await page.locator("#certificate-id").waitFor();
  await page.getByRole("link", { name: "Administrator", exact: true }).click();
  await page.getByRole("heading", { name: "Welcome, administrator" }).waitFor();
});

test("other organizations are view-only and organization input is locked", async t => {
  const { page } = await loginScenario(t);
  const soon = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
  const api = "https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/admin";
  let mutations = 0;
  await page.route(api + "/**", route => {
    if (route.request().method() === "POST") mutations++;
    return route.fulfill({ headers: { "Access-Control-Allow-Origin": origin }, json: route.request().url().endsWith("/session")
      ? { authorized: true, role: "Administrator", organization_id: "org-1", organization: "Organization 1" }
      : { certificates: [
        { certificate_id: "CERT-11111111-1111-4111-8111-111111111111", recipient_name: "Student 1", course_name: "Cloud", organization: "Organization 1", issue_date: "2026-01-01", expiry_date: soon, status: "ACTIVE", can_manage: true },
        { certificate_id: "CERT-22222222-2222-4222-8222-222222222222", recipient_name: "Student 2", course_name: "Cloud", organization: "Organization 2", issue_date: "2026-01-01", expiry_date: "2027-01-01", status: "REVOKED", can_manage: false }
      ], next_cursor: null } });
  });
  await page.getByRole("button", { name: "Check access" }).click();
  await page.getByRole("button", { name: "Load certificates", exact: true }).click();
  await page.getByText("All pages loaded.", { exact: true }).waitFor();
  assert.deepEqual(await page.locator("#certificate-table thead th").allTextContents(), [
    "Recipient", "Organization", "Dates", "Status", "Certificate ID", "Actions"
  ]);
  assert.equal(await page.locator("#certificate-list tr").count(), 2);
  const other = page.locator("#certificate-list tr").filter({ has: page.getByRole("heading", { name: "Student 2", exact: true }) });
  assert.equal(await other.getByRole("button", { name: /Revoke certificate|Retry revocation email/ }).count(), 0);
  assert.equal(await other.getByRole("link", { name: "Verify certificate" }).count(), 1);
  assert.match(await other.textContent(), /View only/);
  assert.equal(await other.locator(".organization-column strong").textContent(), "Organization 2");
  await page.locator("#certificate-organization").selectOption("Organization 2");
  assert.deepEqual(await page.locator("#certificate-list h3").allTextContents(), ["Student 2"]);
  await page.locator("#manageable-only").check();
  assert.equal(await page.locator("#no-matches").isVisible(), true);
  assert.match(await page.locator("#no-matches").textContent(), /cannot manage certificates for Organization 2/);
  await page.getByRole("button", { name: "Clear filters" }).click();
  assert.equal(await page.locator("#certificate-organization").inputValue(), "");
  assert.equal(await page.locator("#manageable-only").isChecked(), false);
  assert.equal(await page.locator("#certificate-list tr").count(), 2);
  await page.locator("#manageable-only").check();
  assert.deepEqual(await page.locator("#certificate-list h3").allTextContents(), ["Student 1"]);
  assert.match(await page.locator(".expiry-warning").textContent(), /Expires in [67] days/);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("button", { name: "Copy certificate ID for Student 1" }).click();
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), "CERT-11111111-1111-4111-8111-111111111111");
  assert.equal(await page.getByLabel("Issuing organization", { exact: true }).inputValue(), "Organization 1");
  assert.equal(await page.getByLabel("Issuing organization", { exact: true }).isEditable(), false);
  assert.equal(mutations, 0);
  await page.screenshot({ path: root + "tmp/admin-organizations-desktop.png", fullPage: true });
});
