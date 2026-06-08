import { beforeEach, describe, expect, test } from "vitest";

import { clearToken, getCsrfToken, getToken, setToken } from "./token";

describe("access token storage (in-memory)", () => {
  beforeEach(() => {
    clearToken();
  });

  test("returns null when nothing is stored", () => {
    expect(getToken()).toBeNull();
  });

  test("round-trips a token through set/get", () => {
    setToken("header.payload.signature");
    expect(getToken()).toBe("header.payload.signature");
  });

  test("clear removes the token", () => {
    setToken("x");
    clearToken();
    expect(getToken()).toBeNull();
  });

  test("does NOT persist to localStorage (memory only)", () => {
    setToken("abc");
    expect(localStorage.getItem("sentinelai.access_token")).toBeNull();
  });
});

describe("getCsrfToken", () => {
  test("reads the sentinelai_csrf cookie, and is null once removed", () => {
    document.cookie = "sentinelai_csrf=tok123";
    expect(getCsrfToken()).toBe("tok123");

    document.cookie = "sentinelai_csrf=; max-age=0";
    expect(getCsrfToken()).toBeNull();
  });
});
