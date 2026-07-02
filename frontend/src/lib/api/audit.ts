import type { AuditCategory, AuditList } from "@/lib/types";
import { request } from "./client";

export interface ListAuditParams {
  category?: AuditCategory[];
  limit?: number;
  offset?: number;
  since?: string;
}

/** Unified audit trail (ADMIN). Merges auth / model / analyst / response events. */
export function listAudit(params: ListAuditParams = {}): Promise<AuditList> {
  const sp = new URLSearchParams();
  for (const c of params.category ?? []) sp.append("category", c);
  if (params.limit != null) sp.set("limit", String(params.limit));
  if (params.offset != null) sp.set("offset", String(params.offset));
  if (params.since) sp.set("since", params.since);
  const query = sp.toString();
  return request<AuditList>(`/audit${query ? `?${query}` : ""}`);
}
