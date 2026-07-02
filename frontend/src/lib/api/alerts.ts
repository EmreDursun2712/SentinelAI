import type {
  Alert,
  AlertClusterList,
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
import { type ListResult, qs, request, requestList } from "./client";

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

/** Paginated alert list: returns items + the total count (from X-Total-Count). */
export function listAlerts(params: ListAlertsParams = {}): Promise<ListResult<Alert>> {
  return requestList<Alert>(`/alerts${qs(params)}`);
}

export function getAlertStats(): Promise<AlertStats> {
  return request<AlertStats>("/alerts/stats");
}

export function getAlertTimeseries(hours = 24): Promise<AlertTimeseries> {
  return request<AlertTimeseries>(`/alerts/timeseries${qs({ hours })}`);
}

/** Correlated incidents: repeated alerts grouped by (source IP, family). */
export function getCorrelatedAlerts(windowHours = 24, limit = 50): Promise<AlertClusterList> {
  return request<AlertClusterList>(`/alerts/correlated${qs({ window_hours: windowHours, limit })}`);
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
