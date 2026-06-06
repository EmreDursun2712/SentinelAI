import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { formatConfidence, formatDateTime, formatPriority } from "@/lib/format";
import type { AlertDetail } from "@/lib/types";

export function AlertOverviewCard({ alert }: { alert: AlertDetail }) {
  const src = `${alert.src_ip}${alert.src_port ? `:${alert.src_port}` : ""}`;
  const dst = `${alert.dst_ip}${alert.dst_port ? `:${alert.dst_port}` : ""}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Alert metadata</CardTitle>
      </CardHeader>
      <dl className="space-y-2 text-sm">
        <Field label="Alert ID" value={`#${alert.id}`} mono />
        <Field label="Source" value={src} mono />
        <Field label="Destination" value={dst} mono />
        <Field label="Protocol" value={alert.protocol ?? "—"} />
        <Field label="Prediction" value={alert.prediction} />
        <Field label="Confidence" value={formatConfidence(alert.confidence)} mono />
        <Field label="Priority" value={formatPriority(alert.priority)} mono />
        <div className="border-t border-slate-800 pt-2">
          <Field label="Created" value={formatDateTime(alert.created_at)} />
          <Field label="Triaged" value={formatDateTime(alert.triaged_at)} />
          <Field label="Responded" value={formatDateTime(alert.responded_at)} />
          <Field label="Investigated" value={formatDateTime(alert.investigated_at)} />
          <Field label="Reported" value={formatDateTime(alert.reported_at)} />
          <Field label="Closed" value={formatDateTime(alert.closed_at)} />
        </div>
      </dl>
    </Card>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-xs uppercase tracking-wider text-slate-500">{label}</dt>
      <dd className={`text-sm text-slate-300 ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
