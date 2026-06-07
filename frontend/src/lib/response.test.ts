import { describe, expect, test } from "vitest";

import type { ResponseActionOut } from "@/lib/types";
import {
  canRollback,
  executionModeLabel,
  executionModeTone,
  isRealLabAction,
} from "./response";

function action(over: Partial<ResponseActionOut>): ResponseActionOut {
  return {
    execution_mode: "SIMULATED",
    simulated: true,
    rollback_status: "NOT_REQUIRED",
    ...over,
  } as ResponseActionOut;
}

describe("response helpers", () => {
  test("simulated action", () => {
    const a = action({});
    expect(isRealLabAction(a)).toBe(false);
    expect(executionModeLabel(a)).toBe("SIMULATED");
    expect(executionModeTone(a)).toBe("neutral");
    expect(canRollback(a)).toBe(false);
  });

  test("real lab action is flagged + rollbackable", () => {
    const a = action({
      execution_mode: "LAB",
      simulated: false,
      rollback_status: "AVAILABLE",
    });
    expect(isRealLabAction(a)).toBe(true);
    expect(executionModeLabel(a)).toBe("LAB · REAL");
    expect(executionModeTone(a)).toBe("danger");
    expect(canRollback(a)).toBe(true);
  });

  test("lab-but-simulated (mock without real effect) is warning, not danger", () => {
    const a = action({ execution_mode: "LAB", simulated: true });
    expect(isRealLabAction(a)).toBe(false);
    expect(executionModeLabel(a)).toBe("LAB");
    expect(executionModeTone(a)).toBe("warning");
  });

  test("rolled-back action is no longer rollbackable", () => {
    expect(canRollback(action({ rollback_status: "ROLLED_BACK" }))).toBe(false);
  });
});
