import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { SeverityPill } from "@/components/SeverityPill";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { alertsApi } from "@/lib/api";
import { formatDuration, formatRelative } from "@/lib/format";

interface Props {
  /** Called when the analyst drills into a cluster's source IP. */
  onSelectSource: (srcIp: string) => void;
}

/**
 * Correlated incidents: collapses repeated alerts from one (source IP, family)
 * into a single row — "one PortScan campaign from 10.0.0.5 (37 alerts)" instead
 * of 37 lines — to cut alert fatigue. Worst severity / highest volume first.
 */
export function IncidentClustersPanel({ onSelectSource }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const q = useQuery({
    queryKey: ["alerts", "correlated", 24],
    queryFn: () => alertsApi.getCorrelatedAlerts(24, 50),
    refetchInterval: 30_000,
  });

  const clusters = q.data?.items ?? [];
  // Only worth showing when correlation actually collapses something.
  const multi = clusters.filter((c) => c.count > 1);
  if (!q.isLoading && multi.length === 0) return null;

  return (
    <Card padding="md">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between text-left"
      >
        <div>
          <h3 className="text-sm font-semibold text-slate-200">
            {t("pages.alerts.correlatedIncidents")}{" "}
            {multi.length > 0 && <span className="text-slate-500">({multi.length})</span>}
          </h3>
          <p className="text-xs text-slate-500">{t("pages.alerts.correlatedHint")}</p>
        </div>
        <span className="text-slate-500">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="mt-3">
          {q.isLoading ? (
            <div className="flex justify-center py-4 text-slate-400">
              <Spinner />
            </div>
          ) : (
            <ul className="space-y-1.5">
              {multi.map((c) => (
                <li key={c.correlation_key}>
                  <button
                    type="button"
                    onClick={() => onSelectSource(c.src_ip)}
                    className="flex w-full items-center gap-3 rounded-md border border-slate-800 bg-slate-900/40 p-2.5 text-left transition hover:border-slate-700 hover:bg-slate-900/70"
                  >
                    <SeverityPill severity={c.max_severity} />
                    <span className="font-mono text-sm text-slate-200">{c.prediction}</span>
                    <span className="text-xs text-slate-500">from</span>
                    <span className="font-mono text-sm text-emerald-300">{c.src_ip}</span>
                    <span className="ml-auto flex items-center gap-2 text-xs text-slate-400">
                      <Badge tone="warning">{c.count} alerts</Badge>
                      {c.open_count > 0 && <span>{c.open_count} open</span>}
                      {c.distinct_destinations > 1 && (
                        <span>{c.distinct_destinations} targets</span>
                      )}
                      <span>· {formatDuration(c.activity_span_seconds)}</span>
                      <span>· {formatRelative(c.last_seen)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}
