import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/cn";
import { alertsApi, investigationApi } from "@/lib/api";
import type { AlertDetail, AlertDisposition } from "@/lib/types";

const ANALYST_ID = "ui-analyst";

const DISPOSITION_BUTTONS: Array<{
  value: AlertDisposition;
  label: string;
  description: string;
  tone: "review" | "confirm" | "fp" | "resolve";
}> = [
  { value: "UNDER_REVIEW", label: "Mark under review", description: "Picking it up", tone: "review" },
  { value: "CONFIRMED", label: "Confirm threat", description: "Real attack", tone: "confirm" },
  {
    value: "FALSE_POSITIVE",
    label: "False positive",
    description: "Auto-closes the alert",
    tone: "fp",
  },
  { value: "RESOLVED", label: "Resolve", description: "Auto-closes the alert", tone: "resolve" },
];

interface AlertActionBarProps {
  alert: AlertDetail;
}

export function AlertActionBar({ alert }: AlertActionBarProps) {
  const qc = useQueryClient();

  const invalidateAlert = () => {
    qc.invalidateQueries({ queryKey: ["alert", alert.id] });
    qc.invalidateQueries({ queryKey: ["alert", alert.id, "investigation"] });
    qc.invalidateQueries({ queryKey: ["alerts"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const dispositionMut = useMutation({
    mutationFn: (d: AlertDisposition) =>
      alertsApi.setAlertDisposition(alert.id, {
        disposition: d,
        analyst_id: ANALYST_ID,
      }),
    onSuccess: invalidateAlert,
  });

  const triageMut = useMutation({
    mutationFn: () => alertsApi.triageAlert(alert.id, {}),
    onSuccess: invalidateAlert,
  });

  const investigateMut = useMutation({
    mutationFn: () => investigationApi.investigateAlert(alert.id, {}),
    onSuccess: invalidateAlert,
  });

  const reportMut = useMutation({
    mutationFn: () => alertsApi.generateAlertReport(alert.id),
    onSuccess: invalidateAlert,
  });

  const closeMut = useMutation({
    mutationFn: () => alertsApi.closeAlert(alert.id, { analyst_id: ANALYST_ID }),
    onSuccess: invalidateAlert,
  });

  const anyDispositionPending = dispositionMut.isPending;
  const anyMutationPending =
    dispositionMut.isPending ||
    triageMut.isPending ||
    investigateMut.isPending ||
    reportMut.isPending ||
    closeMut.isPending;

  return (
    <Card padding="md">
      <div className="space-y-4">
        {/* Disposition row */}
        <div>
          <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-slate-500">
            Analyst disposition · current:{" "}
            <span className="text-slate-300">{alert.disposition}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {DISPOSITION_BUTTONS.map((btn) => {
              const isCurrent = alert.disposition === btn.value;
              return (
                <button
                  key={btn.value}
                  type="button"
                  disabled={anyDispositionPending || isCurrent}
                  onClick={() => dispositionMut.mutate(btn.value)}
                  className={cn(
                    "group flex flex-col items-start gap-0.5 rounded-md border px-3 py-2 text-left transition",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
                    "disabled:cursor-not-allowed",
                    DISPOSITION_TONE[btn.tone],
                    isCurrent && CURRENT_TONE[btn.tone],
                  )}
                >
                  <span className="text-sm font-semibold">
                    {dispositionMut.isPending &&
                      dispositionMut.variables === btn.value && (
                        <Spinner className="mr-1 inline h-3 w-3" />
                      )}
                    {btn.label}
                  </span>
                  <span className="text-[11px] opacity-70">
                    {isCurrent ? "current verdict" : btn.description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Workflow row */}
        <div>
          <p className="mb-2 text-[11px] font-medium uppercase tracking-widest text-slate-500">
            Workflow · current status:{" "}
            <span className="text-slate-300">{alert.status}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={anyMutationPending}
              onClick={() => triageMut.mutate()}
            >
              {triageMut.isPending && <Spinner className="h-3 w-3" />}
              Re-triage
            </Button>
            <Button
              variant="secondary"
              disabled={anyMutationPending}
              onClick={() => investigateMut.mutate()}
            >
              {investigateMut.isPending && <Spinner className="h-3 w-3" />}
              Run investigation
            </Button>
            <Button
              variant="primary"
              disabled={anyMutationPending}
              onClick={() => reportMut.mutate()}
            >
              {reportMut.isPending && <Spinner className="h-3 w-3" />}
              Generate report
            </Button>
            <Button
              variant="ghost"
              disabled={anyMutationPending || alert.status === "CLOSED"}
              onClick={() => closeMut.mutate()}
              className="ml-auto"
            >
              {closeMut.isPending && <Spinner className="h-3 w-3" />}
              Close alert
            </Button>
          </div>
        </div>

        {(dispositionMut.isError ||
          triageMut.isError ||
          investigateMut.isError ||
          reportMut.isError ||
          closeMut.isError) && (
          <p className="text-xs text-rose-400">
            Last action failed — see browser console / network tab for details.
          </p>
        )}
      </div>
    </Card>
  );
}

// Base button tone per disposition type.
const DISPOSITION_TONE: Record<string, string> = {
  review:
    "border-slate-700 bg-slate-800/50 text-slate-200 hover:bg-slate-700/60 focus-visible:ring-slate-500",
  confirm:
    "border-rose-500/30 bg-rose-500/5 text-rose-200 hover:bg-rose-500/10 focus-visible:ring-rose-500",
  fp:
    "border-slate-700 bg-slate-800/50 text-slate-200 hover:bg-slate-700/60 focus-visible:ring-slate-500",
  resolve:
    "border-emerald-500/30 bg-emerald-500/5 text-emerald-200 hover:bg-emerald-500/10 focus-visible:ring-emerald-500",
};

// Highlight applied when the disposition is the current state of the alert.
const CURRENT_TONE: Record<string, string> = {
  review: "ring-1 ring-slate-400 bg-slate-700/60",
  confirm: "ring-1 ring-rose-400 bg-rose-500/15",
  fp: "ring-1 ring-slate-400 bg-slate-700/60",
  resolve: "ring-1 ring-emerald-400 bg-emerald-500/15",
};
