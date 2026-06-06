import { describe, expect, test } from "vitest";

import type { DriftSnapshot } from "@/lib/types";
import { driftReasonText, driftStatusTone, topDriftingFeatures } from "./drift";

describe("driftStatusTone", () => {
  test("maps each status to a badge tone", () => {
    expect(driftStatusTone("OK")).toBe("success");
    expect(driftStatusTone("WATCH")).toBe("warning");
    expect(driftStatusTone("DRIFT")).toBe("danger");
  });
});

describe("driftReasonText", () => {
  test("explains known unavailable reasons", () => {
    expect(driftReasonText("no_snapshot")).toMatch(/no drift check/i);
    expect(driftReasonText("baseline_unavailable")).toMatch(/baseline/i);
    expect(driftReasonText("model_not_loaded")).toMatch(/model/i);
  });

  test("falls back for unknown reasons", () => {
    expect(driftReasonText(null)).toMatch(/unavailable/i);
    expect(driftReasonText("???")).toMatch(/unavailable/i);
  });
});

describe("topDriftingFeatures", () => {
  const snapshot = {
    feature_drift: {
      a: { psi: 0.1, sample_count: 10 },
      b: { psi: 0.5, sample_count: 10 },
      c: { psi: 0.3, sample_count: 10 },
    },
  } as unknown as DriftSnapshot;

  test("sorts by descending PSI and limits", () => {
    expect(topDriftingFeatures(snapshot, 2)).toEqual([
      { feature: "b", psi: 0.5 },
      { feature: "c", psi: 0.3 },
    ]);
  });

  test("handles empty feature_drift", () => {
    expect(topDriftingFeatures({ feature_drift: {} } as unknown as DriftSnapshot)).toEqual(
      [],
    );
  });
});
