import type {
  ActivationResult,
  ModelActivationList,
  ModelVersionList,
  ShadowEval,
} from "@/lib/types";
import { request } from "./client";

/** List registered model versions (lazily synced from artifacts on disk). */
export function listModels(): Promise<ModelVersionList> {
  return request<ModelVersionList>("/models");
}

/** Activate a model version (ADMIN). */
export function activateModel(versionId: number, reason?: string): Promise<ActivationResult> {
  return request<ActivationResult>(`/models/${versionId}/activate`, {
    method: "POST",
    body: { reason: reason ?? null },
  });
}

/** Roll back to the previously active version (ADMIN). */
export function rollbackModel(reason?: string): Promise<ActivationResult> {
  return request<ActivationResult>("/models/rollback", {
    method: "POST",
    body: { reason: reason ?? null },
  });
}

/** Activation / rollback audit history. */
export function listActivations(limit = 50): Promise<ModelActivationList> {
  return request<ModelActivationList>(`/models/activations?limit=${limit}`);
}

/** Run a candidate model over recent events without changing the active one. */
export function shadowEval(
  candidateVersionId: number,
  windowHours = 24,
): Promise<ShadowEval> {
  return request<ShadowEval>("/models/shadow", {
    method: "POST",
    body: { candidate_version_id: candidateVersionId, window_hours: windowHours },
  });
}

/** Recent shadow evaluations. */
export function listShadowEvals(limit = 20): Promise<ShadowEval[]> {
  return request<ShadowEval[]>(`/models/shadow?limit=${limit}`);
}
