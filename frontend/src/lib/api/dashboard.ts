import type { DashboardOverview } from "@/lib/types";
import { request } from "./client";

/** One round trip for every KPI + alert-stats bucket the dashboard needs. */
export function getOverview(): Promise<DashboardOverview> {
  return request<DashboardOverview>("/dashboard/overview");
}
