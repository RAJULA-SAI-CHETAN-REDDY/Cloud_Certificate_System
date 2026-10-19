import { UserManager, WebStorageStateStore } from "oidc-client-ts";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { hideIssuance, showIssuance } from "./issuance.js";
import { hideManagement, showManagement } from "./management.js";

const config = window.ADMIN_CONFIG;
const signIn = document.getElementById("sign-in");
const signOut = document.getElementById("sign-out");
const details = document.getElementById("session-details");
const checkAccess = document.getElementById("check-access");
const backendStatus = document.getElementById("backend-status");
const nonceKey = "ccd.admin.nonce";
let manager;
let keySet;
let expirationTimer;

function requestAccess(user) {
  return fetch(config.sessionApiUrl, {
    headers: { Authorization: user.id_token },
    credentials: "omit",
    cache: "no-store",
    signal: AbortSignal.timeout(15000)
  });
}

function show(status, title, message) {
  hideIssuance();
  hideManagement();
  document.getElementById("workspace-navigation").hidden = true;
  const badge = document.getElementById("session-status");
  badge.dataset.status = status;
  badge.textContent = status === "success" ? "Signed in" : status === "error" ? "Sign-in unavailable" : "Signed out";
  document.getElementById("session-title").textContent = title;
  document.getElementById("session-message").textContent = message;
  details.hidden = true;
  signIn.hidden = false;
  signIn.disabled = false;
  signOut.hidden = true;
  checkAccess.hidden = true;
  backendStatus.hidden = true;
}

async function validateUser(user, expectedNonce) {
  if (!user || user.expired || !user.id_token) throw new Error("Invalid session");
  const { payload } = await jwtVerify(user.id_token, keySet, {
    issuer: config.issuer,
    audience: config.clientId,
    algorithms: ["RS256"],
    requiredClaims: ["exp", "iat", "sub", "token_use"]
  });
  if (payload.token_use !== "id" || !payload.sub ||
      (expectedNonce !== undefined && payload.nonce !== expectedNonce)) {
    throw new Error("Invalid identity");
  }
  if (!Array.isArray(payload["cognito:groups"]) || !payload["cognito:groups"].includes("admins")) {
    await manager.removeUser();
    show("error", "Administrator access required", "This account is not a member of the administrators group.");
    signOut.hidden = false;
    backendStatus.hidden = false;
    backendStatus.textContent = "Checking access restrictions.";
    try {
      const result = await requestAccess(user);
      backendStatus.textContent = result.status === 403
        ? "Administrator access denied by the server."
        : result.status === 401
          ? "The server rejected this session."
          : "Unexpected server response. Administrator access remains blocked.";
    } catch {
      backendStatus.textContent = "Unable to confirm the server response. Administrator access remains blocked.";
    }
    try {
      const result = await fetch(config.issuanceApiUrl, {
        method: "POST", headers: { Authorization: user.id_token, "Content-Type": "application/json" },
        body: "{}", credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(15000)
      });
      backendStatus.textContent += result.status === 403
        ? " Certificate issuance denied by the server."
        : " Certificate issuance restriction was not confirmed. Access remains blocked.";
    } catch {
      backendStatus.textContent += " Unable to confirm the certificate issuance restriction. Access remains blocked.";
    }
    return;
  }
  show("success", "Welcome, administrator", "Your administrator session is active.");
  document.getElementById("session-email").textContent = payload.email || "Not provided";
  const expiresAt = Math.min(payload.exp * 1000, user.expires_at * 1000);
  document.getElementById("session-expiry").textContent = new Date(expiresAt).toLocaleTimeString();
  details.hidden = false;
  signIn.hidden = true;
  signOut.hidden = false;
  checkAccess.hidden = false;
  clearTimeout(expirationTimer);
  expirationTimer = setTimeout(async () => {
    await manager.removeUser();
    show("idle", "Session expired", "Sign in again to continue.");
  }, Math.max(0, expiresAt - Date.now()));
}

signIn.addEventListener("click", async () => {
  signIn.disabled = true;
  try {
    await manager.removeUser();
    await manager.clearStaleState();
    const nonce = Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, "0")).join("");
    sessionStorage.setItem(nonceKey, nonce);
    await manager.signinRedirect({ nonce });
  } catch {
    sessionStorage.removeItem(nonceKey);
    show("error", "Unable to start sign-in", "Please try again. Allow this site to use session storage.");
  }
});

signOut.addEventListener("click", async () => {
  hideManagement();
  hideIssuance();
  signOut.disabled = true;
  try {
    clearTimeout(expirationTimer);
    await manager.removeUser();
    sessionStorage.removeItem(nonceKey);
    const url = new URL("/logout", config.domain);
    url.searchParams.set("client_id", config.clientId);
    url.searchParams.set("logout_uri", config.logoutUri);
    window.location.assign(url.href);
  } catch {
    show("error", "Unable to sign out", "Close this tab to end the local session.");
    signOut.disabled = false;
  }
});

checkAccess.addEventListener("click", async () => {
  hideManagement();
  hideIssuance();
  document.getElementById("workspace-navigation").hidden = true;
  checkAccess.disabled = true;
  backendStatus.hidden = false;
  backendStatus.textContent = "Checking administrator access.";
  try {
    const user = await manager.getUser();
    if (!user || user.expired) {
      await manager.removeUser();
      show("idle", "Session expired", "Sign in again to continue.");
      return;
    }
    const result = await requestAccess(user);
    if (result.status === 401) {
      await manager.removeUser();
      show("idle", "Session expired", "Sign in again to continue.");
      return;
    }
    if (result.status === 403) {
      backendStatus.textContent = "Administrator access was denied.";
      return;
    }
    if (!result.ok) throw new Error("Access check failed");
    const body = await result.json();
    if (body.authorized !== true || body.role !== "Administrator") throw new Error("Invalid response");
    backendStatus.textContent = "Administrator access confirmed by the server.";
    document.getElementById("session-organization").textContent = body.organization || "Not assigned — view only";
    document.getElementById("workspace-navigation").hidden = false;
    showManagement(() => manager.getUser(), async () => {
      await manager.removeUser();
      show("idle", "Session expired", "Sign in again to continue.");
    }, user.profile.sub);
    if (body.organization) showIssuance(() => manager.getUser(), async () => {
      await manager.removeUser();
      show("idle", "Session expired", "Sign in again to continue.");
    }, user.profile.sub, body.organization);
  } catch {
    backendStatus.textContent = "Unable to check access. Please try again.";
  } finally {
    checkAccess.disabled = false;
  }
});

async function initialize() {
  // Capture the callback for validation, then remove codes from browser history.
  const callbackUrl = window.location.href;
  const params = new URL(callbackUrl).searchParams;
  const isCallback = params.has("code") || params.has("error") || params.has("state");
  if (isCallback) history.replaceState(null, "", window.location.pathname);
  try {
    if (window.location.origin + window.location.pathname !== config.redirectUri) {
      show("error", "Open the registered address", "Use the administrator page on the local preview or public website.");
      signIn.disabled = true;
      return;
    }
    manager = new UserManager({
      authority: config.issuer,
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      response_type: "code",
      scope: "openid email",
      automaticSilentRenew: false,
      loadUserInfo: false,
      monitorSession: false,
      requestTimeoutInSeconds: 20,
      userStore: new WebStorageStateStore({ store: sessionStorage }),
      stateStore: new WebStorageStateStore({ store: sessionStorage }),
      metadata: {
        issuer: config.issuer,
        authorization_endpoint: config.domain + "/oauth2/authorize",
        token_endpoint: config.domain + "/oauth2/token",
        jwks_uri: config.issuer + "/.well-known/jwks.json"
      }
    });
    keySet = createRemoteJWKSet(new URL(config.issuer + "/.well-known/jwks.json"));
    if (isCallback) {
      const nonce = sessionStorage.getItem(nonceKey);
      sessionStorage.removeItem(nonceKey);
      if (!nonce) throw new Error("Missing sign-in session");
      const user = await manager.signinRedirectCallback(callbackUrl);
      await validateUser(user, nonce);
    } else {
      const user = await manager.getUser();
      if (user) await validateUser(user);
      else show("idle", "Sign in to your account", "Administrator access only.");
    }
  } catch {
    if (manager) await manager.removeUser().catch(() => {});
    sessionStorage.removeItem(nonceKey);
    show("error", "Sign-in could not be completed", "Your sign-in may have expired or been interrupted. Please sign in again.");
  }
}

initialize();
