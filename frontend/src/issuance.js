const section = document.getElementById("issuance-section");
const form = document.getElementById("issuance-form");
const button = document.getElementById("issue-button");
const message = document.getElementById("issuance-message");
const result = document.getElementById("issued-certificate");
let subject;
let getUser;
let expire;
let submitting = false;

function pendingKey() { return "ccd.issue.pending." + subject; }
function lock(value) { for (const input of form.querySelectorAll("input")) input.disabled = value; }

export function hideIssuance() {
  section.hidden = true;
  result.hidden = true;
}

export function showIssuance(userGetter, onExpired, userSubject, organization) {
  getUser = userGetter;
  expire = onExpired;
  subject = userSubject;
  if (!section.hidden) return;
  section.hidden = false;
  form.reset();
  button.disabled = false;
  form.elements.organization.value = organization;
  lock(false);
  message.textContent = "";
  const saved = sessionStorage.getItem(pendingKey());
  if (saved) {
    try {
      const pending = JSON.parse(saved);
      for (const [name, value] of Object.entries(pending.data)) form.elements.namedItem(name).value = value;
      lock(true);
      if (pending.data.organization !== organization) {
        button.disabled = true;
        message.textContent = "A saved submission uses a different organization. Contact the account owner before retrying; it has not been changed.";
        return;
      }
      button.textContent = "Retry issuance";
      message.textContent = "Your previous submission is ready to retry.";
    } catch { sessionStorage.removeItem(pendingKey()); }
  } else {
    button.disabled = false;
    button.textContent = "Issue certificate";
    const now = new Date();
    form.elements.issue_date.value = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit"
    }).format(now);
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  button.disabled = true;
  result.hidden = true;
  try {
    const user = await getUser();
    if (!user || user.expired || user.profile.sub !== subject) { expire(); return; }
    let pending = JSON.parse(sessionStorage.getItem(pendingKey()) || "null");
    if (!pending) {
      const data = Object.fromEntries(new FormData(form));
      for (const name of Object.keys(data)) data[name] = data[name].trim();
      pending = { key: crypto.randomUUID(), data };
      sessionStorage.setItem(pendingKey(), JSON.stringify(pending));
    }
    lock(true);
    message.textContent = "Issuing certificate.";
    const response = await fetch(window.ADMIN_CONFIG.issuanceApiUrl, {
      method: "POST", credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(25000),
      headers: { Authorization: user.id_token, "Content-Type": "application/json", "Idempotency-Key": pending.key },
      body: JSON.stringify(pending.data)
    });
    if (response.status === 401) { expire(); return; }
    const body = await response.json();
    if (!response.ok) {
      if ([400, 403, 409, 415].includes(response.status)) {
        sessionStorage.removeItem(pendingKey());
        lock(false);
        message.textContent = typeof body.error === "string" ? body.error : "Issuance was not accepted.";
        return;
      }
      throw new Error("Unconfirmed issuance");
    }
    if (!/^CERT-[0-9a-f-]{36}$/.test(body.certificate_id)) throw new Error("Invalid issuance response");
    const verification = new URL(body.verification_url);
    const download = new URL(body.download_url);
    if (verification.origin !== location.origin || verification.pathname !== "/verify.html" ||
        verification.searchParams.get("id") !== body.certificate_id ||
        download.protocol !== "https:" || !download.hostname.endsWith(".amazonaws.com")) {
      throw new Error("Invalid certificate links");
    }
    document.getElementById("issued-id").textContent = body.certificate_id;
    document.getElementById("issued-download").href = download.href;
    document.getElementById("issued-verify").href = verification.href;
    result.hidden = false;
    if (body.notification_status === "pending") {
      message.textContent = "Certificate issued. Email notification pending; retry this submission after one minute. Download is available for five minutes.";
    } else {
      sessionStorage.removeItem(pendingKey());
      lock(false);
      message.textContent = body.notification_status === "published"
        ? "Certificate issued. Email notification queued. Download is available for five minutes."
        : "Certificate issued. Download is available for five minutes.";
    }
  } catch {
    message.textContent = "Issuance could not be confirmed. Retry this submission.";
  } finally {
    submitting = false;
    button.disabled = false;
    button.textContent = sessionStorage.getItem(pendingKey()) ? "Retry issuance" : "Issue certificate";
  }
});
