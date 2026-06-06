import type { DetectionRunSummary, ModelInfo } from "@/lib/types";
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
