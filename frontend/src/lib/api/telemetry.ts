import { API_BASE } from "./client";

export interface ClientErrorReport {
  message: string;
  stack?: string;
  component_stack?: string;
  url?: string;
}

/**
 * Best-effort client-error reporting. Fire-and-forget: never throws, never
 * blocks the UI, and silently no-ops if the backend endpoint is unavailable.
 * The ErrorBoundary always logs to the console regardless.
 */
export function reportClientError(report: ClientErrorReport): void {
  try {
    void fetch(`${API_BASE}/telemetry/client-error`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ ...report, url: report.url ?? window.location.href }),
      keepalive: true,
    }).catch(() => {
      /* ignore — reporting is non-critical */
    });
  } catch {
    /* ignore */
  }
}
