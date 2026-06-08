import { describe, expect, test } from "vitest";

import { checkLabel, isCheckHealthy } from "./readiness";

describe("readiness helpers", () => {
  test("ok/skipped/loaded are healthy; down/unavailable are not", () => {
    expect(isCheckHealthy({ status: "ok" })).toBe(true);
    expect(isCheckHealthy({ status: "skipped" })).toBe(true);
    expect(isCheckHealthy({ status: "loaded" })).toBe(true);
    expect(isCheckHealthy({ status: "down" })).toBe(false);
    expect(isCheckHealthy({ status: "unavailable" })).toBe(false);
    expect(isCheckHealthy(undefined)).toBe(false);
  });

  test("checkLabel returns the status or the fallback", () => {
    expect(checkLabel({ status: "ok" })).toBe("ok");
    expect(checkLabel(undefined)).toBe("…");
    expect(checkLabel(undefined, "down")).toBe("down");
  });
});
