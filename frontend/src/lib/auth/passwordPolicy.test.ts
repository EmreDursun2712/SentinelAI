import { describe, expect, test } from "vitest";

import { isStrongPassword, passwordChecklist, passwordIssues } from "./passwordPolicy";

describe("passwordPolicy", () => {
  test("accepts a strong password", () => {
    expect(isStrongPassword("Str0ng-Passw0rd!", "alice")).toBe(true);
    expect(passwordIssues("Str0ng-Passw0rd!", "alice")).toEqual([]);
  });

  test("rejects too-short passwords", () => {
    expect(isStrongPassword("Ab1!xyz")).toBe(false);
    expect(passwordIssues("Ab1!xyz").join(" ")).toMatch(/12 characters/);
  });

  test("requires at least 3 of 4 categories", () => {
    // all lowercase → only 1 category, long enough
    expect(isStrongPassword("abcdefghijklmnop")).toBe(false);
    expect(passwordIssues("abcdefghijklmnop").join(" ")).toMatch(/lowercase, uppercase/);
    // lowercase + number + symbol = 3 categories ✓
    expect(isStrongPassword("abcdefgh-123")).toBe(true);
  });

  test("rejects passwords containing the username", () => {
    expect(isStrongPassword("Alice-Secret-12", "alice")).toBe(false);
    expect(passwordIssues("Alice-Secret-12", "alice").join(" ")).toMatch(/username/);
  });

  test("checklist reflects which rules pass", () => {
    const checks = passwordChecklist("short", "bob");
    expect(checks.find((c) => c.label.includes("12 characters"))?.ok).toBe(false);
    expect(checks.some((c) => c.label.includes("username"))).toBe(true);
  });
});
