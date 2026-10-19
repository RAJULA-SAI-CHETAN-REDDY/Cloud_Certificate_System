const section = document.getElementById("management-section");
const records = document.getElementById("certificate-list");
const message = document.getElementById("management-message");
const refresh = document.getElementById("refresh-certificates");
const next = document.getElementById("next-certificates");
const search = document.getElementById("certificate-search");
const statusFilter = document.getElementById("certificate-status");
const organizationFilter = document.getElementById("certificate-organization");
const manageableOnly = document.getElementById("manageable-only");
const sort = document.getElementById("certificate-sort");
const summary = document.getElementById("list-summary");
const empty = document.getElementById("no-matches");
const loaded = new Map();
const statusNames = { ACTIVE: "Active", EXPIRED: "Expired", REVOKED: "Revoked", NOT_YET_VALID: "Not yet valid" };
const todayInIndia = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
let getUser, expire, subject, cursor = null, generation = 0, busy = false;

export function hideManagement() {
  generation++;
  section.hidden = true;
  records.replaceChildren();
  loaded.clear();
  search.value = statusFilter.value = "";
  organizationFilter.replaceChildren(new Option("All organizations", ""));
  manageableOnly.checked = false;
  sort.value = "newest";
  summary.textContent = "Load certificates to begin.";
  empty.hidden = true;
  message.textContent = "";
  cursor = null;
  busy = false;
}

export function showManagement(getter, onExpired, userSubject) {
  getUser = getter;
  expire = onExpired;
  subject = userSubject;
  section.hidden = false;
  refresh.disabled = false;
  next.hidden = true;
}

async function request(path, method = "GET") {
  const user = await getUser();
  if (!user || user.expired || user.profile.sub !== subject) { expire(); throw new Error("Sign in again."); }
  const response = await fetch(window.ADMIN_CONFIG.issuanceApiUrl + path, {
    method, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(25000),
    headers: { Authorization: user.id_token }
  });
  if (response.status === 401) { expire(); throw new Error("Sign in again."); }
  if (response.status === 403) {
    if (method === "GET") { expire(); throw new Error("Administrator access denied."); }
    throw new Error("You can manage only your organization's certificates. Reload the list to check your access.");
  }
  if (!response.ok) throw new Error("Operation could not be confirmed. Retry the same certificate or reload the list.");
  return response.json();
}

function render(item) {
  if (!/^CERT-[0-9a-f-]{36}$/.test(item.certificate_id)) throw new Error("Invalid certificate response.");
  const card = document.createElement("article");
  card.className = "certificate-card";
  const heading = document.createElement("h3");
  heading.textContent = item.recipient_name;
  const identifier = document.createElement("p");
  identifier.className = "certificate-id";
  identifier.textContent = item.certificate_id;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "copy-id secondary";
  copy.textContent = "Copy ID";
  copy.setAttribute("aria-label", `Copy certificate ID for ${item.recipient_name}`);
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(item.certificate_id);
      copy.textContent = "Copied";
      setTimeout(() => { if (copy.isConnected) copy.textContent = "Copy ID"; }, 2500);
    } catch { message.textContent = "Could not copy the ID. Select the certificate ID and copy it manually."; }
  });
  const details = document.createElement("dl");
  for (const [label, value] of [["Issued", item.issue_date], ["Valid through", item.expiry_date]]) {
    const term = document.createElement("dt"), detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    details.append(term, detail);
  }
  const status = document.createElement("span");
  status.className = "badge";
  status.dataset.status = item.status;
  status.textContent = statusNames[item.status] || item.status;
  const verify = document.createElement("a");
  verify.textContent = "Verify certificate";
  verify.href = "./verify.html?id=" + encodeURIComponent(item.certificate_id);
  verify.target = "_blank";
  verify.rel = "noopener noreferrer";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  if (item.status !== "REVOKED") button.classList.add("danger");
  button.disabled = item.notification_status === "published";
  button.textContent = item.status === "REVOKED" ? "Retry revocation email" : "Revoke certificate";
  if (button.disabled) button.textContent = "Revocation email queued";
  button.addEventListener("click", async () => {
    if (item.can_manage !== true) return;
    if (busy) return;
    if (item.status !== "REVOKED" && !window.confirm(`Revoke ${item.certificate_id} for ${item.recipient_name}? This cannot be undone. The original PDF will be preserved.`)) return;
    const version = generation;
    busy = true;
    button.disabled = refresh.disabled = next.disabled = true;
    try {
      const result = await request("/" + encodeURIComponent(item.certificate_id) + "/revoke", "POST");
      if (version !== generation) return;
      if (result.certificate_id !== item.certificate_id || result.status !== "REVOKED") throw new Error("Revocation could not be confirmed. Retry the same certificate.");
      item.status = "REVOKED";
      item.notification_status = result.notification_status;
      renderAll();
      message.textContent = result.notification_status === "published"
        ? "Certificate revoked. Email notification queued."
        : "Certificate revoked. Email notification pending; retry after one minute.";
    } catch (error) {
      if (version === generation) message.textContent = error.message;
    } finally {
      if (version === generation) {
        busy = false;
        button.disabled = refresh.disabled = next.disabled = false;
      }
    }
  });
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(verify);
  if (item.can_manage === true) actions.append(button);
  else {
    const readOnly = document.createElement("span");
    readOnly.className = "hint";
    readOnly.textContent = "View only · Managed by another organization";
    actions.append(readOnly);
  }
  const identity = document.createElement("div");
  const course = document.createElement("p");
  course.className = "hint";
  course.textContent = item.course_name;
  identity.append(status, heading, identifier, copy, course);
  if (item.status === "ACTIVE") {
    const today = todayInIndia();
    const days = Math.round((Date.parse(item.expiry_date + "T00:00:00Z") - Date.parse(today + "T00:00:00Z")) / 86400000);
    if (days >= 0 && days <= 30) {
      const expiry = document.createElement("p");
      expiry.className = "expiry-warning";
      expiry.textContent = days === 0 ? "Expires today" : `Expires in ${days} day${days === 1 ? "" : "s"}`;
      identity.append(expiry);
    }
  }
  const organization = document.createElement("div");
  organization.className = "organization-column";
  const organizationLabel = document.createElement("p");
  organizationLabel.className = "column-label";
  organizationLabel.textContent = "Organization";
  const organizationName = document.createElement("strong");
  organizationName.textContent = item.organization;
  const access = document.createElement("p");
  access.className = "hint";
  access.textContent = item.can_manage === true ? "Management access" : "View only";
  organization.append(organizationLabel, organizationName, access);
  card.append(identity, organization, details, actions);
  if (item.can_manage === true && item.status === "REVOKED" && item.notification_status !== "published") {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "Already revoked. Retry email only if needed; this button does not indicate a delivery failure.";
    card.append(hint);
  }
  records.append(card);
}

function renderAll() {
  const selectedOrganization = organizationFilter.value;
  const organizations = [...new Set([...loaded.values()].map(item => item.organization))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  organizationFilter.replaceChildren(new Option("All organizations", ""), ...organizations.map(name => new Option(name, name)));
  organizationFilter.value = organizations.includes(selectedOrganization) ? selectedOrganization : "";
  const term = search.value.trim().toLocaleLowerCase();
  const matches = [...loaded.values()].filter(item =>
    (!statusFilter.value || item.status === statusFilter.value) &&
    (!organizationFilter.value || item.organization === organizationFilter.value) &&
    (!manageableOnly.checked || item.can_manage === true) &&
    [item.recipient_name, item.certificate_id, item.course_name, item.organization].some(value => String(value).toLocaleLowerCase().includes(term)));
  matches.sort((a, b) => sort.value === "recipient" ? a.recipient_name.localeCompare(b.recipient_name)
    : sort.value === "oldest" ? a.issue_date.localeCompare(b.issue_date) : b.issue_date.localeCompare(a.issue_date));
  records.replaceChildren();
  matches.forEach(render);
  empty.hidden = matches.length !== 0;
  if (!matches.length) empty.textContent = manageableOnly.checked && organizationFilter.value &&
    ![...loaded.values()].some(item => item.organization === organizationFilter.value && item.can_manage === true)
    ? `You cannot manage certificates for ${organizationFilter.value}. Clear filters to see other organizations.`
    : "No certificates match these filters. Try another search or clear the filters.";
  summary.textContent = `${matches.length} matching of ${loaded.size} loaded certificates. ` +
    (cursor ? "Filters and sorting cover loaded certificates. Load more to include the remaining pages." : "All pages are loaded.");
}

async function load(reset) {
  if (busy) return;
  const version = generation;
  busy = true;
  refresh.disabled = next.disabled = true;
  message.textContent = "Loading certificates.";
  try {
    const body = await request(!reset && cursor ? "?cursor=" + encodeURIComponent(cursor) : "");
    if (version !== generation) return;
    if (!Array.isArray(body.certificates)) throw new Error("Invalid certificate list.");
    if (reset) loaded.clear();
    body.certificates.forEach(item => loaded.set(item.certificate_id, item));
    cursor = body.next_cursor;
    renderAll();
    next.hidden = !cursor;
    message.textContent = cursor ? "Page loaded. Select Load more to continue." : loaded.size ? "All pages loaded." : "No certificates found.";
  } catch (error) {
    if (version === generation) message.textContent = error.message;
  } finally {
    if (version === generation) {
      busy = false;
      refresh.disabled = next.disabled = false;
    }
  }
}
refresh.addEventListener("click", () => load(true));
next.addEventListener("click", () => load(false));
search.addEventListener("input", renderAll);
statusFilter.addEventListener("change", renderAll);
sort.addEventListener("change", renderAll);
organizationFilter.addEventListener("change", renderAll);
manageableOnly.addEventListener("change", renderAll);
document.getElementById("clear-filters").addEventListener("click", () => {
  search.value = statusFilter.value = organizationFilter.value = "";
  manageableOnly.checked = false;
  sort.value = "newest";
  if (loaded.size) renderAll();
  else { empty.hidden = true; summary.textContent = "Load certificates to begin."; }
});
