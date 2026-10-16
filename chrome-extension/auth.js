// EasyStock Chrome 2.0 — Google sign-in for Firebase Authentication without remote code.
//
// Flow (Manifest V3, service worker):
//   chrome.identity.getAuthToken  →  Google OAuth access token (cached and refreshed by Chrome)
//   Identity Toolkit accounts:signInWithIdp (Firebase Auth REST API)  →  Firebase UID + ID token
//   Realtime Database REST with ?auth=<ID token>  →  users/{uid} only (enforced by Security Rules)
//
// Nothing here is a secret: the OAuth client ID and the Firebase Web API key are public identifiers.
// No client secret, no service account, no refresh token is stored. Tokens are never logged.

export const AUTH_SCOPES = ['openid', 'email', 'profile'];
export const AUTH_BLOCKED = 'BLOCKED_BY_OAUTH_CONFIGURATION';
const PLACEHOLDER = /YOUR_|REPLACE|example/i;
const ID_TOKEN_MARGIN_MS = 2 * 60 * 1000;

export function authConfigStatus(cfg, manifest = {}, runtimeId = '') {
  const missing = [];
  const clientId = String(manifest?.oauth2?.client_id || '');
  if (!clientId || PLACEHOLDER.test(clientId) || !/\.apps\.googleusercontent\.com$/.test(clientId)) missing.push('oauth2.client_id');
  if (!cfg?.firebase_api_key || PLACEHOLDER.test(cfg.firebase_api_key)) missing.push('firebase_api_key');
  if (!/^https:\/\/[a-z0-9-]+(-default-rtdb)?\.(firebaseio\.com|[a-z0-9-]+\.firebasedatabase\.app)$/.test(String(cfg?.database_url || ''))) missing.push('database_url');
  // The OAuth client is bound to the Web Store item ID; an unpacked copy with another ID cannot sign in.
  const expectedId = String(cfg?.extension_id || '');
  const idMismatch = !!(expectedId && runtimeId && runtimeId !== expectedId);
  if (idMismatch) missing.push('extension_id');
  return { ready: missing.length === 0, missing, status: missing.length ? AUTH_BLOCKED : 'READY', runtimeId: runtimeId || '', expectedId, idMismatch };
}

// One readable sentence for the popup; the ID case says exactly what is wrong and what to load.
export function describeBlocked(cfg) {
  if (cfg?.idMismatch) {
    return `目前擴充功能 ID 是 ${cfg.runtimeId}，Google 登入只認商店 ID ${cfg.expectedId}。請改載入已固定 ID 的測試版（dist/oauth-test）或商店版。`;
  }
  const names = { 'oauth2.client_id': 'OAuth Client ID（manifest oauth2）', firebase_api_key: 'Firebase Web API Key', database_url: 'Realtime Database 網址' };
  return `Google 登入待設定：缺少 ${(cfg?.missing || []).map(m => names[m] || m).join('、')}`;
}

export class AuthError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

function friendlyIdentityError(e) {
  const text = String(e?.message || e || '');
  if (/did not approve|canceled|cancelled|user closed|not signed in|rejected/i.test(text)) return new AuthError('CANCELLED', '已取消 Google 授權，本機自選仍可正常使用');
  if (/OAuth2 not granted or revoked/i.test(text)) return new AuthError('CANCELLED', 'Google 授權已撤銷，請重新登入');
  if (/bad client id|invalid client|OAuth2 request failed|Invalid OAuth2 Client ID/i.test(text)) return new AuthError(AUTH_BLOCKED, 'OAuth Client ID 尚未正確設定（需 Chrome 擴充功能類型，綁定正式 Extension ID）');
  if (/interaction required|not interactive|User interaction required/i.test(text)) return new AuthError('REAUTH_REQUIRED', '登入已過期，請重新登入 Google');
  return new AuthError('IDENTITY_ERROR', 'Google 授權失敗，請稍後再試');
}

// Dependencies are injected so the flow is testable without Chrome or the network.
export function createAuth({ identity, fetchImpl = fetch, config, manifest, sessionStore, localStore, runtimeId = '', now = () => Date.now() }) {
  let memorySession = null;

  async function readSession() {
    if (memorySession) return memorySession;
    try { memorySession = (await sessionStore?.get('authSession'))?.authSession || null; } catch (_) { memorySession = null; }
    return memorySession;
  }
  async function writeSession(value) {
    memorySession = value;
    try {
      if (value) await sessionStore?.set({ authSession: value });
      else await sessionStore?.remove?.('authSession');
    } catch (_) { /* session storage unavailable: memory only */ }
  }
  async function readProfile() {
    try { return (await localStore.get('authProfile'))?.authProfile || null; } catch (_) { return null; }
  }

  function status() { return authConfigStatus(config, manifest, runtimeId); }

  async function googleToken(interactive) {
    let result;
    try {
      result = await identity.getAuthToken({ interactive, scopes: AUTH_SCOPES });
    } catch (e) { throw friendlyIdentityError(e); }
    const token = typeof result === 'string' ? result : result?.token;
    if (!token) throw new AuthError(interactive ? 'CANCELLED' : 'REAUTH_REQUIRED', interactive ? '未取得 Google 授權' : '登入已過期，請重新登入 Google');
    return token;
  }

  async function exchange(token) {
    const res = await fetchImpl(`https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=${encodeURIComponent(config.firebase_api_key)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        postBody: `access_token=${encodeURIComponent(token)}&providerId=google.com`,
        requestUri: 'http://localhost',
        returnIdpCredential: false,
        returnSecureToken: true
      }),
      cache: 'no-store', credentials: 'omit'
    });
    let body = null;
    try { body = await res.json(); } catch (_) {}
    if (!res.ok || !body?.idToken || !body?.localId) {
      const code = String(body?.error?.message || res.status);
      const err = new AuthError(/INVALID_IDP_RESPONSE|INVALID_ID_TOKEN|TOKEN_EXPIRED|invalid_token/i.test(code) ? 'GOOGLE_TOKEN_REJECTED'
        : (/OPERATION_NOT_ALLOWED|API key not valid|CONFIGURATION_NOT_FOUND|INVALID_API_KEY/i.test(code) ? AUTH_BLOCKED : 'FIREBASE_AUTH_ERROR'),
        /OPERATION_NOT_ALLOWED/.test(code) ? 'Firebase 尚未啟用 Google 登入供應商'
          : (/API key|CONFIGURATION_NOT_FOUND|INVALID_API_KEY/.test(code) ? 'Firebase Web API Key 設定不正確' : 'Firebase 登入失敗，請稍後再試'));
      err.token = token;
      throw err;
    }
    return body;
  }

  // Sign in (interactive from a user click, silent when renewing an expired ID token).
  // A Google token rejected by Firebase (expired / revoked) is removed from Chrome's cache and
  // retried once — that is how an expired OAuth token recovers without bothering the user.
  async function signIn({ interactive = false } = {}) {
    const cfg = status();
    if (!cfg.ready) throw new AuthError(AUTH_BLOCKED, describeBlocked(cfg));
    let token = await googleToken(interactive);
    let body;
    try {
      body = await exchange(token);
    } catch (e) {
      if (e.code !== 'GOOGLE_TOKEN_REJECTED') throw e;
      try { await identity.removeCachedAuthToken({ token }); } catch (_) {}
      token = await googleToken(interactive);
      body = await exchange(token);
    }
    const expiresIn = Math.max(60, Number(body.expiresIn) || 3600);
    const session = { uid: body.localId, idToken: body.idToken, expiresAt: now() + expiresIn * 1000 };
    const profile = { uid: body.localId, email: String(body.email || ''), displayName: String(body.displayName || body.fullName || ''), signedInAt: new Date(now()).toISOString() };
    await writeSession(session);
    await localStore.set({ authProfile: profile });
    return profile;
  }

  async function getIdToken() {
    const profile = await readProfile();
    if (!profile?.uid) throw new AuthError('SIGNED_OUT', '尚未登入');
    const session = await readSession();
    if (session?.uid === profile.uid && session.expiresAt - ID_TOKEN_MARGIN_MS > now()) return { uid: session.uid, idToken: session.idToken };
    const renewed = await signIn({ interactive: false });
    if (renewed.uid !== profile.uid) {
      // Chrome's Google account changed underneath us: never use the new account with the old data.
      await writeSession(null);
      throw new AuthError('ACCOUNT_CHANGED', 'Chrome 的 Google 帳號已變更，請重新登入');
    }
    const fresh = await readSession();
    return { uid: fresh.uid, idToken: fresh.idToken };
  }

  async function signOut() {
    const session = await readSession();
    await writeSession(null);
    await localStore.remove?.('authProfile');
    try {
      // Drop Chrome's cached Google token for this extension so the next sign-in asks again.
      const cached = await identity.getAuthToken({ interactive: false, scopes: AUTH_SCOPES }).catch(() => null);
      const token = typeof cached === 'string' ? cached : cached?.token;
      if (token) await identity.removeCachedAuthToken({ token });
      if (typeof identity.clearAllCachedAuthTokens === 'function') await identity.clearAllCachedAuthTokens();
    } catch (_) {}
    return { signedOut: true, uid: session?.uid || null };
  }

  return { status, signIn, signOut, getIdToken, profile: readProfile };
}
