import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { InvestigationPacket } from "@/lib/types";

interface InvestigationCardProps {
  packet: InvestigationPacket | null;
}

export function InvestigationCard({ packet }: InvestigationCardProps) {
  if (packet == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Investigation summary</CardTitle>
          <CardDescription>From the investigation agent</CardDescription>
        </CardHeader>
        <EmptyState
          title="No investigation packet yet"
          description='Click "Run investigation" in the action bar to gather evidence.'
        />
      </Card>
    );
  }

  const s = packet.statistics;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigation summary</CardTitle>
        <CardDescription>
          Generated {formatDateTime(packet.generated_at)} ·{" "}
          {packet.model_name
            ? `${packet.model_name}@${packet.model_version}`
            : "no model attached"}
          {packet.truncated && " · results were truncated"}
        </CardDescription>
      </CardHeader>

      <p className="text-sm text-slate-300">{packet.summary}</p>

      {packet.summary_bullets.length > 0 && (
        <ul className="ml-5 mt-3 list-disc space-y-1 text-sm text-slate-400">
          {packet.summary_bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        <Stat label="Related events" value={s.related_event_count} />
        <Stat label="Related alerts" value={s.related_alert_count} />
        <Stat label="Distinct sources" value={s.distinct_source_ips} />
        <Stat label="Distinct targets" value={s.distinct_destination_ips} />
        <Stat label="Same src_ip" value={s.same_src_ip_alert_count} />
        <Stat label="Same dst_ip" value={s.same_dst_ip_alert_count} />
        <Stat label="Same family" value={s.same_family_alert_count} />
        <Stat label="Activity span" value={formatDuration(s.activity_span_seconds)} />
      </div>

      {packet.feature_importance.length > 0 && (
        <details className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-400">
          <summary className="cursor-pointer text-slate-300">
            Top contributing features (global model importance)
          </summary>
          <Table className="mt-2">
            <Thead>
              <Tr>
                <Th>Feature</Th>
                <Th className="text-right">Importance</Th>
              </Tr>
            </Thead>
            <Tbody>
              {packet.feature_importance.slice(0, 10).map((fi) => (
                <Tr key={fi.feature}>
                  <Td className="font-mono text-slate-300">{fi.feature}</Td>
                  <Td className="text-right font-mono">
                    {fi.importance.toFixed(4)}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </details>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900/60 p-2">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-slate-200">{value}</p>
    </div>
  );
}
