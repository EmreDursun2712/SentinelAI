import { Badge } from "@/components/ui/Badge";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import type { AgentDecision } from "@/lib/types";

interface DetectionCardProps {
  decision: AgentDecision | null;
  fallbackConfidence?: number;
  fallbackPrediction?: string;
}

export function DetectionCard({
  decision,
  fallbackConfidence,
  fallbackPrediction,
}: DetectionCardProps) {
  if (decision == null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Detection output</CardTitle>
          <CardDescription>From the ML detection agent</CardDescription>
        </CardHeader>
        <EmptyState
          title="No detection decision recorded"
          description="The alert was created outside the detection pipeline."
        />
      </Card>
    );
  }

  const reasoning = decision.reasoning;
  const predictedLabel =
    (decision.decision.predicted_label as string | undefined) ??
    fallbackPrediction ??
    "—";
  const confidence =
    (decision.decision.confidence as number | undefined) ?? fallbackConfidence ?? 0;
  const threshold = reasoning.threshold as number | undefined;
  const modelName = reasoning.model_name as string | undefined;
  const modelVersion = reasoning.model_version as string | undefined;
  const probabilities = (reasoning.class_probabilities ?? {}) as Record<string, number>;

  const ranked = Object.entries(probabilities).sort((a, b) => b[1] - a[1]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Detection output</CardTitle>
        <CardDescription>From the ML detection agent</CardDescription>
      </CardHeader>

      <dl className="space-y-2 text-sm">
        <Row label="Predicted label">
          <Badge tone="info">{predictedLabel}</Badge>
        </Row>
        <Row label="Confidence">
          <span className="font-mono text-slate-300">{confidence.toFixed(4)}</span>
        </Row>
        <Row label="Threshold">
          <span className="font-mono text-slate-400">
            {threshold != null ? threshold.toFixed(2) : "—"}
          </span>
        </Row>
        <Row label="Model">
          <span className="font-mono text-xs text-slate-400">
            {modelName ? `${modelName}@${modelVersion ?? "?"}` : "—"}
          </span>
        </Row>
      </dl>

      {ranked.length > 0 && (
        <div className="mt-4 border-t border-slate-800 pt-3">
          <p className="mb-2 text-xs uppercase tracking-wider text-slate-500">
            Class probabilities
          </p>
          <Table>
            <Thead>
              <Tr>
                <Th>Class</Th>
                <Th className="text-right">Probability</Th>
              </Tr>
            </Thead>
            <Tbody>
              {ranked.map(([cls, p]) => (
                <Tr key={cls}>
                  <Td className="text-slate-300">{cls}</Td>
                  <Td className="text-right font-mono text-slate-400">
                    {p.toFixed(4)}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </div>
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
