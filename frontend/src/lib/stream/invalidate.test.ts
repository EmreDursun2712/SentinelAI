import { describe, expect, test, vi } from "vitest";

import { applyStreamInvalidation, streamInvalidationKeys } from "./invalidate";

describe("streamInvalidationKeys", () => {
  test("ignores stream control frames", () => {
    expect(streamInvalidationKeys("stream.connected")).toEqual([]);
    expect(streamInvalidationKeys("stream.heartbeat")).toEqual([]);
    expect(streamInvalidationKeys("")).toEqual([]);
  });

  test("alert events refresh dashboard + alert lists + detail", () => {
    expect(streamInvalidationKeys("alert.created")).toEqual([
      ["dashboard"],
      ["alerts"],
      ["alert"],
    ]);
    expect(streamInvalidationKeys("alert.closed")).toEqual([
      ["dashboard"],
      ["alerts"],
      ["alert"],
    ]);
  });

  test("response events refresh response queues + alert detail", () => {
    expect(streamInvalidationKeys("response.action_executed")).toEqual([
      ["dashboard"],
      ["response"],
      ["alert"],
    ]);
  });

  test("report / ingestion / detection map to their query prefixes", () => {
    expect(streamInvalidationKeys("report.created")).toEqual([
      ["dashboard"],
      ["reports"],
    ]);
    expect(streamInvalidationKeys("ingestion.job_completed")).toEqual([
      ["dashboard"],
      ["ingest"],
    ]);
    expect(streamInvalidationKeys("detection.run_completed")).toEqual([
      ["dashboard"],
      ["alerts"],
      ["detection"],
    ]);
  });
});

describe("applyStreamInvalidation", () => {
  test("invalidates each mapped key on the query client", () => {
    const invalidateQueries = vi.fn();
    applyStreamInvalidation({ invalidateQueries }, "alert.created");
    expect(invalidateQueries).toHaveBeenCalledTimes(3);
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["alerts"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["alert"] });
  });

  test("does nothing for control frames", () => {
    const invalidateQueries = vi.fn();
    applyStreamInvalidation({ invalidateQueries }, "stream.heartbeat");
    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
