import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { modelsApi } from "@/lib/api";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { useToast } from "@/lib/toast/ToastContext";
import { formatNumber } from "@/lib/format";
import type {
  PromoteDecision,
  PromoteRecommendation,
  ShadowEval,
} from "@/lib/types";

const DECISION_TONE: Record<PromoteDecision, "success" | "warning" | "neutral"> = {
  promote: "success",
  hold: "warning",
  insufficient_labels: "neutral",
};

/**
 * A/B (shadow) evaluation: run a candidate model over recent labelled traffic
 * without changing what serves, compare per-class F1 against the active model,
 * and surface a promote/hold recommendation. Admins can auto-promote when the
 * candidate clears the active model's macro-F1 by the margin.
 */
export function ShadowEvalPanel() {
  const qc = useQueryClient();
  const toast = useToast();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("ADMIN");
  const canRun = hasRole("ANALYST");
  const [candidateId, setCandidateId] = useState<number | null>(null);
  const [result, setResult] = useState<ShadowEval | null>(null);

  const modelsQ = useQuery({
    queryKey: ["models", "versions"],
    queryFn: modelsApi.listModels,
    refetchInterval: 30_000,
  });

  const versions = modelsQ.data?.items ?? [];
  const activeId = modelsQ.data?.active_version_id ?? null;
  const candidates = versions.filter((v) => !v.is_active);
  const selected = candidateId ?? candidates[0]?.id ?? null;

  const evalMut = useMutation({
    mutationFn: (id: number) => modelsApi.shadowEval(id),
    onSuccess: (res) => {
      setResult(res);
      toast.success("Shadow evaluation complete.");
    },
    onError: (e) => toast.error(errorMessage(e, "Shadow evaluation failed.")),
  });

  const promoteMut = useMutation({
    mutationFn: (id: number) => modelsApi.promoteModel(id),
    onSuccess: (res) => {
      setResult(res.evaluation);
      qc.invalidateQueries({ queryKey: ["models", "versions"] });
      qc.invalidateQueries({ queryKey: ["detection", "model"] });
      toast.success(
        res.promoted
          ? "Candidate promoted — it now serves detection."
          : "Not promoted: recommendation was to hold.",
      );
    },
    onError: (e) => toast.error(errorMessage(e, "Promote failed.")),
  });

  const busy = evalMut.isPending || promoteMut.isPending;
  const recommendation = result?.recommendation ?? result?.metrics?.recommendation ?? null;

  return (
    <Card padding="md">
      <div>
        <h3 className="text-sm font-semibold text-slate-200">A/B model comparison</h3>
        <p className="text-xs text-slate-500">
          Shadow-evaluate a candidate over recent labelled traffic vs. the active model.
        </p>
      </div>

      {candidates.length === 0 ? (
        <p className="mt-4 text-xs text-slate-500">
          Need at least one non-active version to compare. Train and stage another model.
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <Select
              label="Candidate"
              value={selected ?? undefined}
              onChange={(e) => setCandidateId(Number(e.target.value))}
            >
              {candidates.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.version} ({v.algorithm})
                </option>
              ))}
            </Select>
            {canRun && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy || selected == null}
                onClick={() => selected != null && evalMut.mutate(selected)}
              >
                {evalMut.isPending && <Spinner className="h-3 w-3" />}
                Run A/B eval
              </Button>
            )}
            {isAdmin && (
              <Button
                size="sm"
                disabled={busy || selected == null}
                onClick={() => selected != null && promoteMut.mutate(selected)}
              >
                {promoteMut.isPending && <Spinner className="h-3 w-3" />}
                Promote if better
              </Button>
            )}
          </div>

          {result && (
            <ShadowResult result={result} recommendation={recommendation} activeId={activeId} />
          )}
        </>
      )}
    </Card>
  );
}

function ShadowResult({
  result,
  recommendation,
  activeId,
}: {
  result: ShadowEval;
  recommendation: PromoteRecommendation | null;
  activeId: number | null;
}) {
  const m = result.metrics;
  const candEval = m.candidate_eval ?? null;
  const actEval = m.active_eval ?? null;
  const isActiveCandidate = result.candidate_version_id === activeId;

  const classRows = useMemo(() => {
    const labels = new Set<string>([
      ...(candEval?.class_labels ?? []),
      ...(actEval?.class_labels ?? []),
    ]);
    return [...labels].sort().map((label) => ({
      label,
      cand: candEval?.per_class[label]?.f1 ?? null,
      act: actEval?.per_class[label]?.f1 ?? null,
    }));
  }, [candEval, actEval]);

  return (
    <div className="mt-4 space-y-3 border-t border-slate-800 pt-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {recommendation && (
          <Badge tone={DECISION_TONE[recommendation.decision]}>
            {recommendation.decision.replace("_", " ")}
          </Badge>
        )}
        {isActiveCandidate && <Badge tone="neutral">candidate already active</Badge>}
        <span className="text-slate-400">
          agreement{" "}
          <span className="font-mono text-slate-200">
            {result.agreement_rate != null ? `${(result.agreement_rate * 100).toFixed(1)}%` : "—"}
          </span>{" "}
          · {result.sample_count} sample(s)
        </span>
      </div>

      {recommendation && (
        <p className="text-xs text-slate-400">{recommendation.reason}</p>
      )}

      {candEval && actEval ? (
        <div>
          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>Per-class F1 (candidate vs. active)</span>
            <span>
              macro-F1{" "}
              <span className="font-mono text-slate-300">{formatNumber(candEval.macro_f1, 3)}</span>
              {" vs "}
              <span className="font-mono text-slate-300">{formatNumber(actEval.macro_f1, 3)}</span>
            </span>
          </div>
          <Table>
            <Thead>
              <Tr>
                <Th>Class</Th>
                <Th className="text-right">Candidate</Th>
                <Th className="text-right">Active</Th>
                <Th className="text-right">Δ</Th>
              </Tr>
            </Thead>
            <Tbody>
              {classRows.map((r) => {
                const delta = r.cand != null && r.act != null ? r.cand - r.act : null;
                return (
                  <Tr key={r.label}>
                    <Td className="font-mono text-slate-300">{r.label}</Td>
                    <Td className="text-right font-mono">{r.cand != null ? r.cand.toFixed(3) : "—"}</Td>
                    <Td className="text-right font-mono">{r.act != null ? r.act.toFixed(3) : "—"}</Td>
                    <Td
                      className={`text-right font-mono ${
                        delta == null
                          ? "text-slate-500"
                          : delta > 0
                            ? "text-emerald-300"
                            : delta < 0
                              ? "text-rose-300"
                              : "text-slate-400"
                      }`}
                    >
                      {delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`}
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        </div>
      ) : (
        <p className="text-xs text-slate-500">
          No ground-truth labels in this window — agreement shown, but per-class accuracy
          needs labelled events (replay the sample CSV).
        </p>
      )}
    </div>
  );
}
