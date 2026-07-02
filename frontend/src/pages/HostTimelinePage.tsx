import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { SeverityPill } from "@/components/SeverityPill";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { hostsApi } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { TimelineEntry, TimelineKind } from "@/lib/types";

// Kill-chain phase → dot/rail color (Activity → Detection → Triage → Response).
const KIND_COLOR: Record<TimelineKind, string> = {
  flow: "bg-slate-500",
  alert: "bg-rose-500",
  triage: "bg-amber-500",
  response: "bg-emerald-500",
};
const KIND_TONE: Record<TimelineKind, "neutral" | "danger" | "warning" | "success"> = {
  flow: "neutral",
  alert: "danger",
  triage: "warning",
  response: "success",
};

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-slate-200">{value}</p>
    </div>
  );
}

export default function HostTimelinePage() {
  const { ip = "" } = useParams();
  const q = useQuery({
    queryKey: ["hosts", "timeline", ip],
    queryFn: () => hostsApi.getHostTimeline(ip, 24),
    enabled: ip.length > 0,
    refetchInterval: 30_000,
  });

  const data = q.data;
  const s = data?.summary;

  return (
    <section className="space-y-5">
      <PageHeader
        title={`Host timeline — ${ip}`}
        description="Kill-chain view: every flow, alert, and response touching this host over the last 24h, newest first."
      />

      {q.isLoading ? (
        <div className="flex justify-center py-12 text-slate-400">
          <Spinner />
        </div>
      ) : q.isError ? (
        <ErrorState description="Failed to load the host timeline." />
      ) : (
        <>
          {s && (
            <Card padding="md">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                <Stat label="Flows" value={s.event_count} />
                <Stat label="Alerts" value={s.alert_count} />
                <Stat label="Responses" value={s.response_count} />
                <Stat label="Worst severity" value={<SeverityPill severity={s.max_severity} />} />
                <Stat label="Families" value={s.families.length ? s.families.join(", ") : "—"} />
                <Stat
                  label="Last activity"
                  value={s.last_seen ? formatRelative(s.last_seen) : "—"}
                />
              </div>
            </Card>
          )}

          <Card padding="md">
            {!data || data.items.length === 0 ? (
              <EmptyState
                title="No activity"
                description="No flows, alerts, or responses for this host in the window."
              />
            ) : (
              <ol className="relative ml-3 border-l border-slate-800">
                {data.items.map((it, i) => (
                  <TimelineRow key={`${it.kind}-${it.timestamp}-${i}`} entry={it} />
                ))}
              </ol>
            )}
          </Card>
        </>
      )}
    </section>
  );
}

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  return (
    <li className="mb-4 ml-5">
      <span
        className={`absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full ring-2 ring-slate-950 ${
          KIND_COLOR[entry.kind]
        }`}
        aria-hidden="true"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={KIND_TONE[entry.kind]}>{entry.phase}</Badge>
        {entry.severity && <SeverityPill severity={entry.severity} />}
        <span className="text-xs text-slate-500">{formatDateTime(entry.timestamp)}</span>
      </div>
      <p className="mt-1 text-sm text-slate-300">
        {entry.alert_id != null ? (
          <Link to={`/alerts/${entry.alert_id}`} className="hover:underline">
            {entry.title}
          </Link>
        ) : (
          entry.title
        )}
        {entry.label && (
          <span className="ml-2 font-mono text-[11px] text-slate-500">label={entry.label}</span>
        )}
      </p>
    </li>
  );
}
