import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDateTime } from "@/lib/format";
import type { AgentDecision, AgentName } from "@/lib/types";

const AGENT_TONE: Record<AgentName, BadgeTone> = {
  DETECTION: "info",
  TRIAGE: "indigo",
  RESPONSE: "warning",
  INVESTIGATION: "success",
  REPORTING: "default",
  ANALYST: "danger",
};

interface Props {
  decisions: AgentDecision[];
}

export function DecisionChainCard({ decisions }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision chain</CardTitle>
        <CardDescription>
          Audit trail of every agent + analyst action on this alert.
        </CardDescription>
      </CardHeader>

      {decisions.length === 0 ? (
        <EmptyState title="No decisions recorded yet" />
      ) : (
        <ol className="space-y-3">
          {decisions.map((d) => (
            <li
              key={d.id}
              className="rounded-md border border-slate-800 bg-slate-900/60 p-3"
            >
              <div className="flex items-center justify-between text-xs">
                <Badge tone={AGENT_TONE[d.agent] ?? "default"}>{d.agent}</Badge>
                <span className="text-slate-500">
                  {formatDateTime(d.created_at)}
                </span>
              </div>
              <pre className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words text-[11px] font-mono text-slate-400">
                {JSON.stringify(d.decision, null, 2)}
              </pre>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
