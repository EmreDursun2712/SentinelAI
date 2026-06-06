import type { AuthUser, LoginResponse } from "@/lib/types";
import { request } from "./client";

export function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
}

/** Returns the identity encoded in the current token (validates it server-side). */
export function me(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

/** Stateless server-side; the client discards the token regardless of outcome. */
export function logout(): Promise<{ detail: string }> {
  return request<{ detail: string }>("/auth/logout", { method: "POST" });
}
