import { beforeEach, describe, expect, test } from "vitest";

import { clearToken, getToken, setToken } from "./token";

describe("token storage", () => {
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

  test("persists to localStorage under a namespaced key", () => {
    setToken("abc");
    expect(localStorage.getItem("sentinelai.access_token")).toBe("abc");
  });
});
