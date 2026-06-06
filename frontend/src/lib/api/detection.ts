import type {
  DetectionRunSummary,
  DriftHistory,
  DriftReport,
  ModelInfo,
} from "@/lib/types";
import { request } from "./client";

export function getModelInfo(): Promise<ModelInfo> {
  return request<ModelInfo>("/detection/model");
}

export function runDetection(
  body: { limit?: number } = {},
): Promise<DetectionRunSummary> {
  return request<DetectionRunSummary>("/detection/run", {
    method: "POST",
    body: { limit: body.limit ?? 1000 },
  });
}

export function getLatestDrift(): Promise<DriftReport> {
  return request<DriftReport>("/detection/drift/latest");
}

export function runDrift(body: { window_hours?: number } = {}): Promise<DriftReport> {
  return request<DriftReport>("/detection/drift/run", {
    method: "POST",
    body: { window_hours: body.window_hours ?? 24 },
  });
}

export function getDriftHistory(limit = 20): Promise<DriftHistory> {
  return request<DriftHistory>(`/detection/drift/history?limit=${limit}`);
}
