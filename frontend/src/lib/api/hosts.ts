import type { HostTimeline } from "@/lib/types";
import { qs, request } from "./client";

/** Kill-chain attack timeline (flows + alerts + responses) for one host/IP. */
export function getHostTimeline(ip: string, windowHours = 24): Promise<HostTimeline> {
  return request<HostTimeline>(`/hosts/${encodeURIComponent(ip)}/timeline${qs({ window_hours: windowHours })}`);
}
