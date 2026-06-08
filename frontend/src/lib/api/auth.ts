import type { AuthUser, Role } from "@/lib/types";
import type { LoginResponse } from "@/lib/types";
import { request } from "./client";

export interface CreatedUser {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
}

/** Exchange credentials for an access token; the server also sets the refresh
 *  + CSRF cookies. */
export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

/** Rotate the refresh cookie and obtain a fresh access token. Normally driven
 *  automatically by the API client's 401 handler; exposed for explicit use. */
export function refresh(): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/refresh", { method: "POST" });
}

/** Current identity. With no in-memory access token, the client's 401 handler
 *  refreshes from the cookie first — so this also bootstraps the session. */
export function me(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

/** Revoke the current refresh session and clear cookies. */
export function logout(): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/logout", { method: "POST" });
}

/** Revoke every session for the user (sign out of all devices). */
export function logoutAll(): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/logout-all", { method: "POST" });
}

/** Create a user (ADMIN only). The backend enforces the password policy. */
export function createUser(
  username: string,
  password: string,
  role: Role,
): Promise<CreatedUser> {
  return request<CreatedUser>("/auth/users", {
    method: "POST",
    body: { username, password, role },
  });
}
