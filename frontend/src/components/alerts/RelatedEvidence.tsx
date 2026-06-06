import { Link } from "react-router-dom";

import { SeverityPill } from "@/components/SeverityPill";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { formatDateTimeShort, formatRelative } from "@/lib/format";
import type { InvestigationPacket } from "@/lib/types";

interface Props {
  packet: InvestigationPacket | null;
}

export function RelatedEvidence({ packet }: Props) {
  if (packet == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Related evidence</CardTitle>
          <CardDescription>
            Surrounding alerts and flow records from the investigation packet.
          </CardDescription>
        </CardHeader>
        <EmptyState
          title="No investigation packet yet"
          description="Run an investigation to populate related events and alerts."
        />
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card padding="none">
        <div className="border-b border-slate-800 px-5 py-3">
          <CardTitle>Related alerts</CardTitle>
          <CardDescription>
            {packet.related_alerts.length} alert(s) within the lookback window.
          </CardDescription>
        </div>
        {packet.related_alerts.length === 0 ? (
          <EmptyState title="No related alerts" />
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>ID</Th>
                <Th>Severity</Th>
                <Th>Prediction</Th>
                <Th>Source</Th>
                <Th>Age</Th>
              </Tr>
            </Thead>
            <Tbody>
              {packet.related_alerts.slice(0, 20).map((a) => (
                <Tr key={a.id}>
                  <Td>
                    <Link
                      to={`/alerts/${a.id}`}
                      className="font-mono text-emerald-400 hover:underline"
                    >
                      #{a.id}
                    </Link>
                  </Td>
                  <Td>
                    <SeverityPill severity={a.severity} />
                  </Td>
                  <Td className="text-slate-300">{a.prediction}</Td>
                  <Td className="font-mono text-xs text-slate-400">{a.src_ip}</Td>
                  <Td className="text-xs text-slate-500">
                    {formatRelative(a.created_at)}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      <Card padding="none">
        <div className="border-b border-slate-800 px-5 py-3">
          <CardTitle>Related events</CardTitle>
          <CardDescription>
            {packet.related_events.length} flow(s) in ±
            {packet.events_window_minutes} minutes.
          </CardDescription>
        </div>
        {packet.related_events.length === 0 ? (
          <EmptyState title="No related events" />
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>Time (UTC)</Th>
                <Th>Source → Target</Th>
                <Th>Label</Th>
              </Tr>
            </Thead>
            <Tbody>
              {packet.related_events.slice(0, 20).map((e) => (
                <Tr key={e.id}>
                  <Td className="font-mono text-xs text-slate-400">
                    {formatDateTimeShort(e.event_time)}
                  </Td>
                  <Td className="font-mono text-xs text-slate-400">
                    {e.src_ip}
                    {e.src_port ? `:${e.src_port}` : ""}
                    <span className="mx-1 text-slate-600">→</span>
                    {e.dst_ip}
                    {e.dst_port ? `:${e.dst_port}` : ""}
                  </Td>
                  <Td className="text-xs text-slate-300">{e.label ?? "—"}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
