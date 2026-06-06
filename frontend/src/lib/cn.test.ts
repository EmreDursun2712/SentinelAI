import { describe, expect, test } from "vitest";

import { cn } from "./cn";

describe("cn", () => {
  test("joins plain strings with a single space", () => {
    expect(cn("a", "b", "c")).toBe("a b c");
  });

  test("drops falsy values", () => {
    expect(cn("a", undefined, null, false, "", "b")).toBe("a b");
  });

  test("handles object syntax (clsx)", () => {
    expect(cn("a", { b: true, c: false })).toBe("a b");
  });

  test("dedupes conflicting tailwind utilities (tailwind-merge)", () => {
    // tailwind-merge collapses conflicting padding classes — last wins.
    expect(cn("p-2", "p-4")).toBe("p-4");
    expect(cn("text-red-500", "text-blue-500")).toBe("text-blue-500");
  });

  test("preserves non-conflicting classes side by side", () => {
    expect(cn("p-2", "m-2")).toBe("p-2 m-2");
  });
});
