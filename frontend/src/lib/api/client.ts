// Low-level fetch client used by every resource module under lib/api/.
// All resource calls go through `request` so the error envelope, base URL,
// JSON parsing, the Bearer header, and 401 handling live in one place.

import { clearToken, getToken, notifyUnauthorized } from "@/lib/auth/token";

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

async function _fetch(url: string, init: RequestInitWithBody = {}): Promise<Response> {
  const { body, headers, ...rest } = init;
  const hasJsonBody = body !== undefined && body !== null && !(body instanceof FormData);
  const token = getToken();
  return fetch(url, {
    ...rest,
    headers: {
      ...(hasJsonBody ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

/** Call a path relative to the versioned API base. */
export async function request<T>(
  path: string,
  init: RequestInitWithBody = {},
): Promise<T> {
  const response = await _fetch(`${API_BASE}${path}`, init);
  const requestId = response.headers.get("x-request-id") ?? undefined;
  const parsed = await _parse(response);
  if (!response.ok) {
    // A 401 means our token is missing/expired/invalid: drop it and let the
    // AuthProvider redirect to /login. (403 = authenticated but not allowed —
    // we keep the session and surface the error to the caller as usual.)
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
