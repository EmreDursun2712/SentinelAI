import { describe, expect, test } from "vitest";

import { ApiError } from "./client";
import {
  errorMessage,
  isAuthError,
  isRateLimited,
  retryAfterSeconds,
  shouldRetry,
} from "./errors";

const rateLimited = new ApiError(429, {
  error: { code: "rate_limited", message: "slow down", details: { retry_after: 12 } },
});
const forbidden = new ApiError(403, { error: { code: "forbidden", message: "nope" } });
const unauthorized = new ApiError(401, { error: { code: "unauthorized" } });
const serverError = new ApiError(500, {
  error: { code: "internal_error", message: "Internal server error." },
});

describe("error classification", () => {
  test("isRateLimited", () => {
    expect(isRateLimited(rateLimited)).toBe(true);
    expect(isRateLimited(forbidden)).toBe(false);
    expect(isRateLimited(new Error("x"))).toBe(false);
  });

  test("isAuthError covers 401 and 403", () => {
    expect(isAuthError(unauthorized)).toBe(true);
    expect(isAuthError(forbidden)).toBe(true);
    expect(isAuthError(rateLimited)).toBe(false);
  });

  test("retryAfterSeconds reads the envelope detail", () => {
    expect(retryAfterSeconds(rateLimited)).toBe(12);
    expect(retryAfterSeconds(forbidden)).toBeNull();
  });
});

describe("errorMessage", () => {
  test("429 mentions the retry window", () => {
    expect(errorMessage(rateLimited)).toContain("12s");
    expect(errorMessage(rateLimited).toLowerCase()).toContain("rate limit");
  });

  test("403 and 401 have dedicated copy", () => {
    expect(errorMessage(forbidden).toLowerCase()).toContain("permission");
    expect(errorMessage(unauthorized).toLowerCase()).toContain("session");
  });

  test("falls back to the envelope message, then the default", () => {
    expect(errorMessage(serverError)).toBe("Internal server error.");
    expect(errorMessage(new Error("boom"), "default")).toBe("default");
  });
});

describe("shouldRetry", () => {
  test("never retries client errors including 429", () => {
    expect(shouldRetry(0, rateLimited)).toBe(false);
    expect(shouldRetry(0, forbidden)).toBe(false);
    expect(shouldRetry(0, unauthorized)).toBe(false);
  });

  test("retries other failures once", () => {
    expect(shouldRetry(0, serverError)).toBe(true);
    expect(shouldRetry(1, serverError)).toBe(false);
    expect(shouldRetry(0, new Error("network"))).toBe(true);
  });
});
