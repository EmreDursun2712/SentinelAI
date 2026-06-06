import type { BadgeTone } from "@/components/ui/Badge";
import type { DriftSnapshot, DriftStatus } from "@/lib/types";

export function driftStatusTone(status: DriftStatus): BadgeTone {
  switch (status) {
    case "OK":
      return "success";
    case "WATCH":
      return "warning";
    case "DRIFT":
      return "danger";
    default:
      return "neutral";
  }
}

export interface TopFeature {
  feature: string;
  psi: number;
}

/** Features sorted by descending PSI (most-drifted first). */
export function topDriftingFeatures(snapshot: DriftSnapshot, n = 5): TopFeature[] {
  return Object.entries(snapshot.feature_drift ?? {})
    .map(([feature, d]) => ({ feature, psi: d.psi }))
    .sort((a, b) => b.psi - a.psi)
    .slice(0, n);
}

/** Human-readable explanation for an unavailable drift report. */
export function driftReasonText(reason: string | null): string {
  switch (reason) {
    case "no_snapshot":
      return "No drift check has been run yet.";
    case "baseline_unavailable":
      return "This model has no training baseline — retrain to enable drift monitoring.";
    case "model_not_loaded":
      return "No detection model is loaded.";
    case "no_recent_data":
      return "No recent traffic to analyze in the window.";
    case "insufficient_data":
      return "Not enough recent data to compute drift.";
    default:
      return "Drift monitoring is unavailable.";
  }
}
