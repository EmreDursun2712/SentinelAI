import { SeverityPill } from "@/components/SeverityPill";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatPriority } from "@/lib/format";
import type { AgentDecision, AlertDetail } from "@/lib/types";

interface TriageCardProps {
  alert: AlertDetail;
  decision: AgentDecision | null;
}

export function TriageCard({ alert, decision }: TriageCardProps) {
  if (decision == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Triage result</CardTitle>
          <CardDescription>From the triage rule engine</CardDescription>
        </CardHeader>
        <EmptyState
          title="Not yet triaged"
          description='Use "Re-triage" in the action bar to score this alert.'
        />
      </Card>
    );
  }

  const explanations = (decision.reasoning.explanations as string[] | undefined) ?? [];
  const factors = (decision.reasoning.factors ?? {}) as Record<string, unknown>;
  const recentCount = decision.decision.recent_count as number | undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Triage result</CardTitle>
        <CardDescription>From the triage rule engine</CardDescription>
      </CardHeader>

      <dl className="space-y-2 text-sm">
        <Row label="Severity">
          <SeverityPill severity={alert.severity} />
        </Row>
        <Row label="Priority">
          <span className="font-mono text-slate-300">
            {formatPriority(alert.priority)}
          </span>
        </Row>
        <Row label="Recent src_ip alerts">
          <span className="font-mono text-slate-400">{recentCount ?? "—"}</span>
        </Row>
      </dl>

      {explanations.length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <p className="mb-2 text-xs uppercase tracking-wider text-slate-500">
            Factors
          </p>
          <ul className="space-y-1 text-xs text-slate-400">
            {explanations.map((e, i) => (
              <li key={i} className="font-mono">
                • {e}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Object.keys(factors).length > 0 && (
        <details className="mt-3 text-xs text-slate-500">
          <summary className="cursor-pointer text-slate-400">Raw factors</summary>
          <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap break-words rounded bg-slate-950/60 p-2 font-mono text-[11px]">
            {JSON.stringify(factors, null, 2)}
          </pre>
        </details>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-xs uppercase tracking-wider text-slate-500">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
