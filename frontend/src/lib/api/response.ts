import type {
  ResponseActionOut,
  ResponseActionType,
  ResponseStatus,
} from "@/lib/types";
import { qs, request } from "./client";

export interface ListActionsParams {
  alert_id?: number;
  status?: ResponseStatus;
  action_type?: ResponseActionType;
  limit?: number;
  offset?: number;
}

export function listResponseActions(
  params: ListActionsParams = {},
): Promise<ResponseActionOut[]> {
  return request<ResponseActionOut[]>(`/response${qs(params)}`);
}

export function listPendingActions(limit = 100): Promise<ResponseActionOut[]> {
  return request<ResponseActionOut[]>(`/response/pending${qs({ limit })}`);
}

export function getResponseAction(id: number): Promise<ResponseActionOut> {
  return request<ResponseActionOut>(`/response/${id}`);
}

export function approveResponseAction(
  id: number,
  body: { analyst_id?: string; note?: string } = {},
): Promise<ResponseActionOut> {
  return request<ResponseActionOut>(`/response/${id}/approve`, {
    method: "POST",
    body,
  });
}

export function rejectResponseAction(
  id: number,
  body: { reason: string; analyst_id?: string },
): Promise<ResponseActionOut> {
  return request<ResponseActionOut>(`/response/${id}/reject`, {
    method: "POST",
    body,
  });
}

export function generateRecommendations(alertId: number): Promise<{
  alert_id: number;
  actions: ResponseActionOut[];
}> {
  return request<{ alert_id: number; actions: ResponseActionOut[] }>(
    `/response/recommend/${alertId}`,
    { method: "POST" },
  );
}
