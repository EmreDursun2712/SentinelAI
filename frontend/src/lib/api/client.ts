// Low-level fetch client used by every resource module under lib/api/.
// All resource calls go through `request`, so the error envelope, base URL,
// JSON parsing, the Bearer header, cookie credentials, the CSRF header, and the
// refresh-on-401 flow all live in one place.

import {
  clearToken,
  getCsrfToken,
  getToken,
  notifyUnauthorized,
  setToken,
} from "@/lib/auth/token";

export const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

// Strip /api/v1 to reach the root for /health and /readyz.
export const API_ROOT: string = API_BASE.replace(/\/api\/v1$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    public readonly requestId?: string,
  ) {
    super(`API request failed with status ${status}`);
    this.name = "ApiError";
  }
}

type RequestInitWithBody = Omit<RequestInit, "body"> & { body?: unknown };

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

// Paths (relative to API_BASE) that must never trigger an automatic refresh —
// refresh itself, plus the credential-exchange endpoints.
const NO_REFRESH_PATHS = new Set(["/auth/refresh", "/auth/login", "/auth/logout"]);

async function _fetch(url: string, init: RequestInitWithBody = {}): Promise<Response> {
  const { body, headers, ...rest } = init;
  const hasJsonBody = body !== undefined && body !== null && !(body instanceof FormData);
  const token = getToken();
  const method = (rest.method ?? "GET").toUpperCase();
  const csrf = SAFE_METHODS.has(method) ? null : getCsrfToken();
  return fetch(url, {
    ...rest,
    // Send/receive the httpOnly refresh + CSRF cookies (cross-origin in dev).
    credentials: "include",
    headers: {
      ...(hasJsonBody ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...headers,
    },
    body:
      body === undefined || body === null
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
}

async function _parse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// Single-flight refresh: many requests can 401 at once (e.g. on load); they all
// await the same /auth/refresh call instead of stampeding it.
let refreshInFlight: Promise<boolean> | null = null;

function attemptRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await _fetch(`${API_BASE}/auth/refresh`, { method: "POST" });
        if (!res.ok) return false;
        const data = (await _parse(res)) as { access_token?: string } | null;
        if (data?.access_token) {
          setToken(data.access_token);
          return true;
        }
        return false;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/** Call a path relative to the versioned API base. */
export async function request<T>(path: string, init: RequestInitWithBody = {}): Promise<T> {
  let response = await _fetch(`${API_BASE}${path}`, init);

  // On 401, try refreshing the session once (using the httpOnly refresh cookie),
  // then replay the original request. Skip for the auth endpoints themselves.
  if (response.status === 401 && !NO_REFRESH_PATHS.has(path)) {
    const refreshed = await attemptRefresh();
    if (refreshed) {
      response = await _fetch(`${API_BASE}${path}`, init);
    }
  }

  const requestId = response.headers.get("x-request-id") ?? undefined;
  const parsed = await _parse(response);
  if (!response.ok) {
    // A surviving 401 means the session is gone: drop the in-memory token and
    // let the AuthProvider redirect to /login. (403 = authenticated but not
    // allowed — keep the session and surface the error to the caller.)
    if (response.status === 401) {
      clearToken();
      notifyUnauthorized();
    }
    throw new ApiError(response.status, parsed, requestId);
  }
  return parsed as T;
}

/** Call a path relative to the API root (used for /health and /readyz only). */
export async function rootRequest<T>(
  path: string,
  init: RequestInitWithBody = {},
  acceptCodes: number[] = [200],
): Promise<T> {
  const response = await _fetch(`${API_ROOT}${path}`, init);
  const parsed = await _parse(response);
  if (!acceptCodes.includes(response.status) && !response.ok) {
    throw new ApiError(response.status, parsed);
  }
  return parsed as T;
}

/** Build a URL with a query-string from a record, skipping undefined/null/"". */
export function qs(params: object): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params as Record<string, unknown>)) {
    if (value === undefined || value === null || value === "") continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}
