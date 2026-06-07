import type { BadgeTone } from "@/components/ui/Badge";
import type { ResponseActionOut } from "@/lib/types";

/** A *real* lab effect (LAB mode and not simulated) — the one to flag loudly. */
export function isRealLabAction(action: ResponseActionOut): boolean {
  return action.execution_mode === "LAB" && !action.simulated;
}

export function executionModeLabel(action: ResponseActionOut): string {
  if (isRealLabAction(action)) return "LAB · REAL";
  if (action.execution_mode === "LAB") return "LAB";
  return "SIMULATED";
}

export function executionModeTone(action: ResponseActionOut): BadgeTone {
  if (isRealLabAction(action)) return "danger";
  if (action.execution_mode === "LAB") return "warning";
  return "neutral";
}

/** Eligible for rollback: a real lab effect still in place. */
export function canRollback(action: ResponseActionOut): boolean {
  return action.rollback_status === "AVAILABLE";
}

export const LAB_APPROVE_WARNING =
  "This will affect the configured lab environment.";
