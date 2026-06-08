import type { DependencyCheck } from "@/lib/types";

// Statuses that mean "healthy / not a problem" for a dependency pill.
const HEALTHY = new Set(["ok", "skipped", "loaded"]);

/** True if a readiness dependency check should render as healthy. */
export function isCheckHealthy(check?: DependencyCheck): boolean {
  return check ? HEALTHY.has(check.status) : false;
}

/** Short text for a dependency pill (the raw status, or a placeholder). */
export function checkLabel(check: DependencyCheck | undefined, fallback = "…"): string {
  return check?.status ?? fallback;
}
