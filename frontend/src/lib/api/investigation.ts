import type { InvestigationEnvelope } from "@/lib/types";
import { request } from "./client";

export interface InvestigateBody {
  events_window_minutes?: number;
  alerts_window_hours?: number;
  max_events?: number;
  max_alerts?: number;
}

export function investigateAlert(
  alertId: number,
  body: InvestigateBody = {},
): Promise<InvestigationEnvelope> {
  return request<InvestigationEnvelope>(`/alerts/${alertId}/investigate`, {
    method: "POST",
    body,
  });
}

export function getAlertInvestigation(
  alertId: number,
): Promise<InvestigationEnvelope> {
  return request<InvestigationEnvelope>(`/alerts/${alertId}/investigation`);
}
