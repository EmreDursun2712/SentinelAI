import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { detectionApi } from "@/lib/api";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { driftReasonText, driftStatusTone, topDriftingFeatures } from "@/lib/drift";
import { formatConfidence, formatNumber, formatRelative } from "@/lib/format";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-slate-200">{value}</p>
    </div>
  );
}

export function ModelHealthPanel() {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canRun = hasRole("ANALYST");

  const driftQ = useQuery({
    queryKey: ["detection", "drift"],
    queryFn: detectionApi.getLatestDrift,
    refetchInterval: 60_000,
  });

  const runMut = useMutation({
    mutationFn: () => detectionApi.runDrift({ window_hours: 24 }),
    onSuccess: (report) => {
      qc.setQueryData(["detection", "drift"], report);
      qc.invalidateQueries({ queryKey: ["detection", "drift"] });
    },
  });

  const runButton = canRun ? (
    <Button
      size="sm"
      variant="secondary"
      onClick={() => runMut.mutate()}
      disabled={runMut.isPending}
    >
      {runMut.isPending && <Spinner className="h-3 w-3" />}
      Run drift check
    </Button>
  ) : null;

  const report = driftQ.data;
  const snapshot = report?.snapshot;

  return (
    <Card padding="none">
      <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">Model health</h3>
          {report?.available && snapshot && (
            <Badge tone={driftStatusTone(snapshot.status)}>{snapshot.status}</Badge>
          )}
          {report && !report.available && <Badge tone="neutral">unavailable</Badge>}
        </div>
        {runButton}
      </div>

      <div className="p-5">
        {driftQ.isLoading ? (
          <div className="flex justify-center py-6 text-slate-400">
            <Spinner />
          </div>
        ) : driftQ.isError ? (
          <ErrorState description="Failed to load model drift status." />
        ) : report && report.available && snapshot ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Stat
                label="Model"
                value={
                  report.model_name
                    ? `${report.model_name}@${report.model_version}`
                    : "—"
                }
              />
              <Stat
                label="Drift score"
                value={
                  snapshot.drift_score !== null
                    ? formatNumber(snapshot.drift_score, 3)
                    : "—"
                }
              />
              <Stat label="Samples (24h)" value={formatNumber(snapshot.sample_count)} />
              <Stat
                label="Avg confidence"
                value={formatConfidence(snapshot.confidence_stats.mean)}
              />
              <Stat label="Last checked" value={formatRelative(snapshot.created_at)} />
              <Stat
                label="Features tracked"
                value={formatNumber(Object.keys(snapshot.feature_drift).length)}
              />
            </div>

            {topDriftingFeatures(snapshot).length > 0 && (
              <div>
                <p className="mb-1.5 text-[10px] uppercase tracking-widest text-slate-500">
                  Top drifting features (PSI)
                </p>
                <ul className="space-y-1">
                  {topDriftingFeatures(snapshot).map((f) => (
                    <li
                      key={f.feature}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="font-mono text-slate-300">{f.feature}</span>
                      <span
                        className={
                          f.psi >= 0.25
                            ? "text-rose-300"
                            : f.psi >= 0.1
                              ? "text-amber-300"
                              : "text-slate-400"
                        }
                      >
                        {formatNumber(f.psi, 3)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2 py-2 text-center">
            <p className="text-sm text-slate-300">
              {driftReasonText(report?.reason ?? null)}
            </p>
            {report?.model_name && (
              <p className="text-xs text-slate-500">
                Current model: {report.model_name}@{report.model_version}
              </p>
            )}
            {!canRun && (
              <p className="text-xs text-slate-500">
                An analyst can run a drift check.
              </p>
            )}
          </div>
        )}

        {runMut.isError && (
          <p className="mt-3 text-xs text-rose-400">
            {errorMessage(runMut.error, "Drift check failed.")}
          </p>
        )}
      </div>
    </Card>
  );
}
