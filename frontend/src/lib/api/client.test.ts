import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { clearToken, getToken, setToken, UNAUTHORIZED_EVENT } from "@/lib/auth/token";
import { ApiError, request } from "./client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === null ? "" : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function headersOf(call: unknown[]): Record<string, string> {
  return (call[1] as RequestInit).headers as Record<string, string>;
}

describe("api client", () => {
  beforeEach(() => {
    clearToken();
    document.cookie = "sentinelai_csrf=; max-age=0";
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("on 401 it refreshes once and replays the original request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: "x" }, 401)) // original → 401
      .mockResolvedValueOnce(jsonResponse({ access_token: "newtok" }, 200)) // /auth/refresh
      .mockResolvedValueOnce(jsonResponse({ ok: true }, 200)); // replay
    vi.stubGlobal("fetch", fetchMock);

    const data = await request<{ ok: boolean }>("/alerts");

    expect(data).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getToken()).toBe("newtok");
    // The refresh call hit /auth/refresh …
    expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/refresh");
    // … and the replay carried the fresh Bearer token.
    expect(headersOf(fetchMock.mock.calls[2]).Authorization).toBe("Bearer newtok");
  });

  test("when refresh also fails, it clears the token and notifies once", async () => {
    setToken("stale");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: "x" }, 401)) // original → 401
      .mockResolvedValueOnce(jsonResponse({ error: "x" }, 401)); // refresh → 401
    vi.stubGlobal("fetch", fetchMock);

    const onUnauthorized = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);

    await expect(request("/alerts")).rejects.toBeInstanceOf(ApiError);

    expect(getToken()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalled();
    window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  });

  test("attaches the X-CSRF-Token header on unsafe methods", async () => {
    document.cookie = "sentinelai_csrf=csrf123";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await request("/response/approve/1", { method: "POST", body: {} });

    expect(headersOf(fetchMock.mock.calls[0])["X-CSRF-Token"]).toBe("csrf123");
  });

  test("does not send a CSRF header on safe (GET) requests", async () => {
    document.cookie = "sentinelai_csrf=csrf123";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }, 200));
    vi.stubGlobal("fetch", fetchMock);

    await request("/alerts");

    expect(headersOf(fetchMock.mock.calls[0])["X-CSRF-Token"]).toBeUndefined();
  });
});
