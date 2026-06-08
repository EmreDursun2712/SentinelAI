import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { authApi } from "@/lib/api";
import type { AuthUser, Role } from "@/lib/types";
import { UNAUTHORIZED_EVENT, clearToken, setToken } from "@/lib/auth/token";

interface AuthContextValue {
  user: AuthUser | null;
  /** True until the initial session check completes (avoids login-flash on reload). */
  loading: boolean;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Sign out of every device (revokes all refresh sessions + access tokens). */
  logoutAll: () => Promise<void>;
  /** True if the user's role meets or exceeds `min` (VIEWER < ANALYST < ADMIN). */
  hasRole: (min: Role) => boolean;
}

const RANK: Record<Role, number> = { VIEWER: 1, ANALYST: 2, ADMIN: 3 };

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  // On mount: probe /auth/me. With no in-memory access token, the API client's
  // 401 handler first tries /auth/refresh using the httpOnly cookie — so this
  // restores the session across reloads without any token in storage.
  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) {
          clearToken();
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // The API client fires this when the session is gone (refresh failed).
  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await authApi.login(username, password);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // best-effort; local state is cleared regardless
    }
    clearToken();
    setUser(null);
  }, []);

  const logoutAll = useCallback(async () => {
    try {
      await authApi.logoutAll();
    } catch {
      // best-effort; local state is cleared regardless
    }
    clearToken();
    setUser(null);
  }, []);

  const hasRole = useCallback(
    (min: Role) => (user ? RANK[user.role] >= RANK[min] : false),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: user !== null,
      login,
      logout,
      logoutAll,
      hasRole,
    }),
    [user, loading, login, logout, logoutAll, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used within an <AuthProvider>.");
  }
  return ctx;
}
