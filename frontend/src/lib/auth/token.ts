// Access-token storage — IN MEMORY ONLY (no localStorage/sessionStorage).
//
// The access token is short-lived and held only in this module variable, so it
// never survives a reload and is never exposed to other tabs or to XSS via
// storage. The durable session lives in an httpOnly refresh cookie the JS can't
// read; on reload the API client silently calls /auth/refresh to mint a new
// access token from that cookie. The token is attached as a Bearer header by the
// API client and is also used to authenticate the WebSocket (?token=).

let accessToken: string | null = null;

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string): void {
  accessToken = token;
}

export function clearToken(): void {
  accessToken = null;
}

// ----- CSRF (double-submit) ------------------------------------------------

const CSRF_COOKIE = "sentinelai_csrf";

/** Read the readable CSRF cookie set by the backend, or null if absent. */
export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return null;
}

// Broadcast name used by the API client to tell the AuthProvider that the
// session is gone (refresh failed) so it can drop state and redirect.
export const UNAUTHORIZED_EVENT = "sentinelai:unauthorized";

export function notifyUnauthorized(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}
