// Access-token storage.
//
// We store the JWT in localStorage. An httpOnly cookie would be more
// XSS-resistant, but it requires server-set cookies + CSRF protection — a
// larger change than this etap. To keep the localStorage approach defensible:
//   - the token lives under a single, namespaced key and nothing else;
//   - it is read only here and attached as a Bearer header by the API client;
//   - it is never written to logs or the DOM;
//   - the React app sets a strict-ish surface (no dangerouslySetInnerHTML on
//     user data), keeping the XSS attack surface small.
// Rotate to httpOnly cookies if this ever leaves the classroom/lab.

const TOKEN_KEY = "sentinelai.access_token";

// In-memory mirror so a single render pass doesn't hit localStorage repeatedly,
// and so the app keeps working if storage is unavailable (private mode, etc.).
let cached: string | null | undefined;

export function getToken(): string | null {
  if (cached !== undefined) return cached;
  try {
    cached = localStorage.getItem(TOKEN_KEY);
  } catch {
    cached = null;
  }
  return cached;
}

export function setToken(token: string): void {
  cached = token;
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage unavailable — fall back to the in-memory mirror for this session.
  }
}

export function clearToken(): void {
  cached = null;
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

// Broadcast name used by the API client to tell the AuthProvider that the
// server rejected our token (401) so it can drop the session and redirect.
export const UNAUTHORIZED_EVENT = "sentinelai:unauthorized";

export function notifyUnauthorized(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}
