import type {
  Alert,
  AlertDetail,
  AlertDisposition,
  AlertStats,
  AlertTimeseries,
  ReportEnvelope,
  Severity,
  TriageOut,
  UpdateDispositionBody,
} from "@/lib/types";
import type { AlertStatus } from "@/lib/types";
import { qs, request } from "./client";

export interface ListAlertsParams {
  status?: AlertStatus;
  severity?: Severity;
  disposition?: AlertDisposition;
  src_ip?: string;
  dst_ip?: string;
  prediction?: string;
  min_priority?: number;
  q?: string;
  sort?: "created_at" | "priority" | "severity";
  limit?: number;
  offset?: number;
}

export function listAlerts(params: ListAlertsParams = {}): Promise<Alert[]> {
  return request<Alert[]>(`/alerts${qs(params)}`);
}

export function getAlertStats(): Promise<AlertStats> {
  return request<AlertStats>("/alerts/stats");
}

export function getAlertTimeseries(hours = 24): Promise<AlertTimeseries> {
  return request<AlertTimeseries>(`/alerts/timeseries${qs({ hours })}`);
}

export function getAlert(id: number): Promise<AlertDetail> {
  return request<AlertDetail>(`/alerts/${id}`);
}

export function triageAlert(
  id: number,
  body: { window_minutes?: number } = {},
): Promise<TriageOut> {
  return request<TriageOut>(`/alerts/${id}/triage`, {
    method: "POST",
    body,
  });
}

export function setAlertDisposition(
  id: number,
  body: UpdateDispositionBody,
): Promise<Alert> {
  return request<Alert>(`/alerts/${id}/disposition`, {
    method: "POST",
    body,
  });
}

export function closeAlert(
  id: number,
  body: { analyst_id?: string; note?: string } = {},
): Promise<Alert> {
  return request<Alert>(`/alerts/${id}/close`, { method: "POST", body });
}

export function generateAlertReport(id: number): Promise<ReportEnvelope> {
  return request<ReportEnvelope>(`/alerts/${id}/report`, { method: "POST" });
}

export function getAlertReport(id: number): Promise<ReportEnvelope> {
  return request<ReportEnvelope>(`/alerts/${id}/report`);
}
