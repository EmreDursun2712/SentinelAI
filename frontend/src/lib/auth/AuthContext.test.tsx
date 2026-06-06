import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  authApi: {
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

import { authApi } from "@/lib/api";
import { AuthProvider, useAuth } from "./AuthContext";
import { clearToken, getToken } from "./token";

const wrapper = ({ children }: { children: ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

describe("AuthContext", () => {
  beforeEach(() => {
    clearToken();
    vi.clearAllMocks();
  });

  test("is unauthenticated when no token is stored", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(authApi.me).not.toHaveBeenCalled();
  });

  test("login stores the token and exposes the user + role checks", async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      expires_at: "2030-01-01T00:00:00Z",
      user: { username: "alice", role: "ANALYST" },
    });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.login("alice", "pw");
    });

    expect(getToken()).toBe("tok");
    expect(result.current.user).toEqual({ username: "alice", role: "ANALYST" });
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.hasRole("VIEWER")).toBe(true);
    expect(result.current.hasRole("ANALYST")).toBe(true);
    expect(result.current.hasRole("ADMIN")).toBe(false);
  });

  test("logout clears the token and user", async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: "tok",
      token_type: "bearer",
      expires_at: "2030-01-01T00:00:00Z",
      user: { username: "bob", role: "ADMIN" },
    });
    vi.mocked(authApi.logout).mockResolvedValue({ detail: "ok" });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.login("bob", "pw");
    });
    expect(result.current.hasRole("ADMIN")).toBe(true);

    await act(async () => {
      await result.current.logout();
    });

    expect(getToken()).toBeNull();
    expect(result.current.user).toBeNull();
    expect(result.current.isAuthenticated).toBe(false);
  });

  test("validates an existing token on mount via /me", async () => {
    vi.mocked(authApi.me).mockResolvedValue({ username: "carol", role: "VIEWER" });
    // Seed a token so the provider attempts validation.
    const { setToken } = await import("./token");
    setToken("preexisting");

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(authApi.me).toHaveBeenCalledOnce();
    expect(result.current.user).toEqual({ username: "carol", role: "VIEWER" });
    expect(result.current.hasRole("ANALYST")).toBe(false);
  });
});
