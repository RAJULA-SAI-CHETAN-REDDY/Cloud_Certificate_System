import { getDocument, GlobalWorkerOptions } from "pdfjs-dist/build/pdf.mjs";
import jsQR from "jsqr";

GlobalWorkerOptions.workerSrc = "./js/pdf.worker.min.mjs";

const form = document.getElementById("scan-form");
const picker = document.getElementById("scan-file");
const button = document.getElementById("scan-button");
const result = document.getElementById("scan-result");
const idPattern = /CERT-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
const maxBytes = 12 * 1024 * 1024;

function show(kind, text) {
  result.dataset.result = kind;
  result.textContent = text;
}

function candidateIds(text) {
  const ids = new Set(text.match(idPattern) || []);
  try {
    const url = new URL(text);
    const id = url.searchParams.get("id");
    if (id && /^CERT-[0-9a-f-]{36}$/.test(id)) ids.add(id);
  } catch { /* The QR value may be a plain ID. */ }
  return ids;
}

function readQr(canvas) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
  return jsQR(pixels.data, pixels.width, pixels.height)?.data || "";
}

async function scanImage(file) {
  const image = await createImageBitmap(file);
  try {
    if (image.width * image.height > 30000000) throw new Error("This image is too large to scan. Use a smaller image or enter the ID above.");
    const scale = Math.min(1, 2400 / Math.max(image.width, image.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(image.width * scale));
    canvas.height = Math.max(1, Math.round(image.height * scale));
    canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
    return candidateIds(readQr(canvas));
  } finally { image.close(); }
}

async function scanPdf(bytes) {
  const documentTask = getDocument({ data: new Uint8Array(bytes.slice(0)) });
  const pdf = await documentTask.promise;
  const ids = new Set();
  try {
    for (let pageNumber = 1; pageNumber <= Math.min(pdf.numPages, 5); pageNumber++) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const strings = content.items.map(item => item.str || "");
      for (const id of candidateIds(strings.join(" "))) ids.add(id);
      for (const id of candidateIds(strings.join(""))) ids.add(id);
      if (!ids.size) {
        const viewport = page.getViewport({ scale: 2 });
        if (viewport.width * viewport.height > 16000000) continue;
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
        for (const id of candidateIds(readQr(canvas))) ids.add(id);
      }
    }
  } finally { await documentTask.destroy(); }
  return ids;
}

async function lookup(url) {
  const response = await fetch(url, { credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(15000) });
  const body = await response.json();
  if (!response.ok && !(response.status === 404 && body.status === "NOT_FOUND"))
    throw new Error(body.error || "Verification is unavailable. Try again later.");
  return body;
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  const file = picker.files?.[0];
  if (!file || button.disabled) return;
  button.disabled = true;
  show("loading", "Reading the file…");
  try {
    if (file.size > maxBytes) throw new Error("Choose a file smaller than 12 MB.");
    const pdf = file.type === "application/pdf" || /\.pdf$/i.test(file.name);
    const image = ["image/png", "image/jpeg", "image/webp"].includes(file.type);
    if (!pdf && !image) throw new Error("Choose a PDF, PNG, JPEG or WebP file.");
    const bytes = pdf ? await file.arrayBuffer() : null;
    const ids = pdf ? await scanPdf(bytes) : await scanImage(file);
    if (!ids.size) throw new Error(image ? "No QR code found. Enter the printed certificate ID above." : "No certificate ID or QR code found in the first five PDF pages. Enter the ID above.");
    if (ids.size > 1) throw new Error("This file contains more than one certificate ID. Enter the intended ID above.");
    const id = [...ids][0];
    const api = window.CERTIFICATE_CONFIG?.verificationApiUrl;
    if (!api) throw new Error("Verification is not configured.");
    show("loading", `Checking ${id} against the certificate record…`);
    const record = await lookup(`${api.replace(/\/$/, "")}/${encodeURIComponent(id)}`);
    if (record.status === "NOT_FOUND") { show("mismatch", `${id}: no certificate record found.`); return; }
    if (!pdf) {
      show(record.status === "ACTIVE" ? "match" : "mismatch", `${id}: record status ${record.status}. The QR code identifies a record; this image is not proof that the original PDF is unchanged.`);
      return;
    }
    const fingerprint = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map(b => b.toString(16).padStart(2, "0")).join("");
    const checked = await lookup(`${api.replace(/\/$/, "")}/${encodeURIComponent(id)}?sha256=${fingerprint}`);
    if (checked.pdf_match === true) show(record.status === "ACTIVE" ? "match" : "mismatch", `${id}: exact issued PDF confirmed. Current record status: ${record.status}.`);
    else if (checked.pdf_match === false) show("mismatch", `${id}: this PDF differs from the issued original. Record status: ${record.status}.`);
    else show("error", `${id}: record status ${record.status}. Exact PDF comparison is unavailable for this certificate.`);
  } catch (error) {
    show("error", error.message || "Could not read the file. Try another copy or enter the certificate ID above.");
  } finally { button.disabled = false; }
});
