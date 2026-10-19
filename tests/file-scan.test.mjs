import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { before, after, test } from "node:test";
import { createRequire } from "node:module";
import { spawn, execFileSync } from "node:child_process";
import { browserOptions, python, root } from "./browser-runtime.mjs";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");
const origin = "http://localhost:8001";
const id = "CERT-fe669248-fea3-564f-9e01-f9c6211ec503";
let server, browser;

before(async () => {
  await mkdir(root + "tmp", { recursive: true });
  server = spawn(python, ["backend/local_server.py", "--port", "8001", "--records-dir", "output/generic-samples"], { cwd: root, windowsHide: true, stdio: "ignore" });
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(origin + "/verify.html")).ok) break; } catch {}
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

test("original PDF matches while altered bytes do not", async t => {
  const context = await browser.newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  const original = execFileSync(python, ["-c", "from backend.generate_certificate import generate_certificate; import sys; sys.stdout.buffer.write(generate_certificate('CI Demo Student', 'Cloud Computing', 'Organization 1', '2026-10-19', '2027-10-19', 'http://localhost:8000/verify.html', certificate_id='" + id + "')[0])"], { cwd: root });
  const fingerprint = createHash("sha256").update(original).digest("hex");
  await page.route("https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/verify/**", route => {
    const supplied = new URL(route.request().url()).searchParams.get("sha256");
    return route.fulfill({ headers: { "Access-Control-Allow-Origin": "*" },
      json: { certificate_id: id, status: "ACTIVE", ...(supplied && { pdf_match: supplied === fingerprint }) } });
  });
  await page.goto(origin + "/verify.html");
  await page.locator("#scan-file").setInputFiles({ name: "certificate.pdf", mimeType: "application/pdf", buffer: original });
  await page.getByRole("button", { name: "Check file" }).click();
  await page.waitForFunction(() => !document.querySelector("#scan-result").textContent.includes("Reading") && !document.querySelector("#scan-result").textContent.includes("Checking"));
  assert.match(await page.locator("#scan-result").textContent(), /exact issued PDF confirmed/);
  await page.screenshot({ path: root + "tmp/file-scan-desktop.png", fullPage: true });
  assert.equal(await page.locator("#scan-result").getAttribute("data-result"), "match");
  await page.locator("#scan-file").setInputFiles({ name: "altered.pdf", mimeType: "application/pdf", buffer: Buffer.concat([original, Buffer.from("\nchanged")]) });
  await page.getByRole("button", { name: "Check file" }).click();
  await page.getByText(/this PDF differs from the issued original/).waitFor();
  assert.equal(await page.locator("#scan-result").getAttribute("data-result"), "mismatch");
});

test("QR image identifies the record without claiming file authenticity", async t => {
  const context = await browser.newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  await page.route("https://v8wddxhk67.execute-api.ap-south-1.amazonaws.com/dev/verify/**", route => route.fulfill({
    headers: { "Access-Control-Allow-Origin": "*" }, json: { certificate_id: id, status: "ACTIVE" }
  }));
  const png = execFileSync(python, ["-c", "import io,qrcode,sys; b=io.BytesIO(); qrcode.make('http://localhost:8000/verify.html?id=" + id + "').save(b,format='PNG'); sys.stdout.buffer.write(b.getvalue())"], { cwd: root });
  await page.goto(origin + "/verify.html");
  await page.locator("#scan-file").setInputFiles({ name: "code.png", mimeType: "image/png", buffer: png });
  await page.getByRole("button", { name: "Check file" }).click();
  await page.getByText(/this image is not proof that the original PDF is unchanged/).waitFor();
  assert.match(await page.locator("#scan-result").textContent(), /record status ACTIVE/);
});

test("optional live API smoke check for the existing sample PDF", { skip: !process.env.CCD_LIVE_SCAN_API }, async t => {
  const context = await browser.newContext();
  t.after(() => context.close());
  const page = await context.newPage();
  await page.goto(origin + "/verify.html");
  const original = await readFile(root + "output/generic-samples/" + id + ".pdf");
  await page.locator("#scan-file").setInputFiles({ name: "certificate.pdf", mimeType: "application/pdf", buffer: original });
  await page.getByRole("button", { name: "Check file" }).click();
  await page.getByText(/exact issued PDF confirmed/).waitFor();
  assert.match(await page.locator("#scan-result").textContent(), /Current record status: ACTIVE/);
});
