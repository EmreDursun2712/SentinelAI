import { request } from "./client";

export interface DemoResetResult {
  reset: boolean;
  cleared: Record<string, number>;
}

/** ADMIN-only demo helper: wipe operational data so the dashboard returns to
 * zero. 404s unless the backend has the demo-reset feature enabled. */
export function resetDemo(): Promise<DemoResetResult> {
  return request<DemoResetResult>("/admin/reset-demo", { method: "POST" });
}
