import { describe, expect, test } from "vitest";

import {
  formatConfidence,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPriority,
  formatRelative,
} from "./format";

describe("formatDateTime", () => {
  test("renders ISO UTC timestamps in YYYY-MM-DD HH:MM:SS UTC form", () => {
    expect(formatDateTime("2026-05-23T08:23:14Z")).toBe("2026-05-23 08:23:14 UTC");
  });
  test("returns em-dash for null / undefined / invalid", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});

describe("formatDuration", () => {
  test("returns em-dash for null / undefined", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
  test("uses ms below 1s", () => {
    expect(formatDuration(0.25)).toContain("ms");
  });
  test("uses s in [1, 60)", () => {
    expect(formatDuration(45.7)).toContain("s");
    expect(formatDuration(45.7)).not.toContain("min");
  });
  test("uses min in [60, 3600)", () => {
    expect(formatDuration(120)).toContain("min");
  });
  test("uses h in [3600, 86400)", () => {
    expect(formatDuration(7200)).toContain("h");
  });
  test("uses d at and above 1 day", () => {
    expect(formatDuration(172800)).toContain("d");
  });
});

describe("formatConfidence + formatPriority + formatNumber", () => {
  test("confidence has 4 decimals", () => {
    expect(formatConfidence(0.92345)).toBe("0.9234");
    expect(formatConfidence(null)).toBe("—");
  });
  test("priority has 1 decimal", () => {
    expect(formatPriority(67.0)).toBe("67.0");
    expect(formatPriority(undefined)).toBe("—");
  });
  test("formatNumber handles NaN and missing values", () => {
    expect(formatNumber(NaN)).toBe("—");
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(3.14159, 2)).toBe("3.14");
  });
});

describe("formatRelative", () => {
  test("returns em-dash for null", () => {
    expect(formatRelative(null)).toBe("—");
  });
  test("uses seconds for recent", () => {
    const tenSecondsAgo = new Date(Date.now() - 10_000).toISOString();
    expect(formatRelative(tenSecondsAgo)).toContain("s ago");
  });
  test("uses minutes after 1 minute", () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    expect(formatRelative(fiveMinutesAgo)).toContain("m ago");
  });
  test("uses hours after 1 hour", () => {
    const twoHoursAgo = new Date(Date.now() - 2 * 3_600_000).toISOString();
    expect(formatRelative(twoHoursAgo)).toContain("h ago");
  });
});
