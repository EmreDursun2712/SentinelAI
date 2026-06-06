// Shared helpers for turning ApiError into user-facing messages and for
// deciding whether a failed request should be retried. Keeping this in one
// place means 401/403/429 are handled consistently across the app.

import { ApiError } from "./client";

export function isRateLimited(error: unknown): boolean {
  return error instanceof ApiError && error.status === 429;
}

export function isAuthError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 403);
}

/** Retry-After seconds from a 429 response, if the server provided details. */
export function retryAfterSeconds(error: unknown): number | null {
  if (error instanceof ApiError && error.status === 429) {
    const body = error.body as { error?: { details?: { retry_after?: number } } } | null;
    const ra = body?.error?.details?.retry_after;
    if (typeof ra === "number" && Number.isFinite(ra)) return ra;
  }
  return null;
}

/** A concise, human-friendly message for any error. */
export function errorMessage(error: unknown, fallback = "Something went wrong."): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      const ra = retryAfterSeconds(error);
      return ra
        ? `Rate limit exceeded — try again in ~${ra}s.`
        : "Rate limit exceeded — slow down and try again shortly.";
    }
    if (error.status === 403) return "You don't have permission to do that.";
    if (error.status === 401) return "Your session expired. Please sign in again.";
    const body = error.body as { error?: { message?: string } } | null;
    if (body?.error?.message) return body.error.message;
  }
  return fallback;
}

// TanStack Query retry predicate: never retry client errors (incl. 429 — that
// would just burn the budget faster); retry other failures once.
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (
    error instanceof ApiError &&
    [400, 401, 403, 404, 422, 429].includes(error.status)
  ) {
    return false;
  }
  return failureCount < 1;
}
