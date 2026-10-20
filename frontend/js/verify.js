"use strict";
const form = document.getElementById("verify-form");
const input = document.getElementById("certificate-id");
const button = document.getElementById("verify-button");
const result = document.getElementById("result");
const details = document.getElementById("details");
const download = document.getElementById("certificate-download");
const states = {
  ACTIVE: ["Valid", "Certificate is valid", "This certificate is recorded and is within its validity dates."],
  EXPIRED: ["Expired", "Certificate has expired", "A matching record exists, but its expiry date has passed."],
  REVOKED: ["Revoked", "Certificate has been revoked", "The issuer has marked this certificate as revoked."],
  NOT_YET_VALID: ["Not yet valid", "Validity has not started", "The issue date for this certificate is in the future."],
  NOT_FOUND: ["Not found", "No matching certificate", "Check the ID against the certificate and try again."]
};

function show(status, title, message, label) {
  result.hidden = false;
  const badge = document.getElementById("status-label");
  badge.textContent = label;
  badge.dataset.status = status;
  document.getElementById("result-title").textContent = title;
  document.getElementById("result-message").textContent = message;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (button.disabled) return;
  const id = input.value.trim();
  details.replaceChildren();
  details.hidden = true;
  download.hidden = true;
  download.removeAttribute("href");
  button.disabled = true;
  button.textContent = "Checking…";
  show("LOADING", "Checking certificate", "Please wait while we check the record.", "Checking");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const apiUrl = window.CERTIFICATE_CONFIG?.verificationApiUrl;
    if (!apiUrl) throw new Error("Verification is not configured. Please contact the site administrator.");
    const response = await fetch(`${apiUrl.replace(/\/$/, "")}/${encodeURIComponent(id)}`, {
      credentials: "omit", signal: controller.signal
    });
    const data = await response.json();
    if (!response.ok && !(response.status === 404 && data.status === "NOT_FOUND")) {
    throw new Error(response.status === 429 ? "Too many requests. Please wait a moment and try again." : (data.error || "Unable to verify right now. Please try again."));
    }
    const state = states[data.status];
    if (!state) throw new Error("Unexpected verification response. Please try again.");
    show(data.status, state[1], state[2], state[0]);
    if (data.status !== "NOT_FOUND") {
      for (const [key, label] of [["recipient_name", "Recipient"], ["course_name", "Course"], ["organization", "Issued by"], ["issue_date", "Issue date"], ["expiry_date", "Expiry date"], ["certificate_id", "Certificate ID"]]) {
        const term = document.createElement("dt");
        const value = document.createElement("dd");
        term.textContent = label;
        value.textContent = data[key];
        details.append(term, value);
      }
      details.hidden = false;
      download.href = `${apiUrl.replace(/\/$/, "")}/${encodeURIComponent(id)}?download=1`;
      download.hidden = false;
    }
    history.replaceState(null, "", `/verify.html?id=${encodeURIComponent(id)}`);
  } catch (error) {
    show("ERROR", "Unable to verify", error.name === "AbortError" ? "The request timed out. Please try again." : error.message, "Try again");
  } finally {
    clearTimeout(timeout);
    button.disabled = false;
    button.textContent = "Verify certificate";
  }
});

const initialId = new URLSearchParams(location.search).get("id");
if (location.protocol === "file:") {
  button.disabled = true;
  show("ERROR", "Open the local verification website", "Start backend/local_server.py, then open http://localhost:8000/verify.html. Verification needs the local server running.", "Server required");
} else if (initialId) {
  input.value = initialId;
  form.requestSubmit();
}
