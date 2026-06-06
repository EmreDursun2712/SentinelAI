import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { AlertActionBar } from "@/components/alerts/AlertActionBar";
import { AlertOverviewCard } from "@/components/alerts/AlertOverviewCard";
import { DecisionChainCard } from "@/components/alerts/DecisionChainCard";
import { DetectionCard } from "@/components/alerts/DetectionCard";
import { InvestigationCard } from "@/components/alerts/InvestigationCard";
import { RelatedEvidence } from "@/components/alerts/RelatedEvidence";
import { ResponseActionsTable } from "@/components/alerts/ResponseActionsTable";
import { TriageCard } from "@/components/alerts/TriageCard";
import { DispositionPill } from "@/components/DispositionPill";
import { SeverityPill } from "@/components/SeverityPill";
import { StatusPill } from "@/components/StatusPill";
import { ApiError } from "@/lib/api";
import { ErrorState } from "@/components/ui/ErrorState";
import { Spinner } from "@/components/ui/Spinner";
import { alertsApi, investigationApi } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function AlertDetailPage() {
  const { id } = useParams();
  const alertId = Number(id);

  const alertQ = useQuery({
    queryKey: ["alert", alertId],
    queryFn: () => alertsApi.getAlert(alertId),
    enabled: Number.isFinite(alertId),
  });
  const investigationQ = useQuery({
    queryKey: ["alert", alertId, "investigation"],
    queryFn: () => investigationApi.getAlertInvestigation(alertId),
    enabled: Number.isFinite(alertId),
    // 404 is the "no packet yet" path — don't retry; the empty state handles it.
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });

  if (!Number.isFinite(alertId)) {
    return <ErrorState title="Invalid alert id" />;
  }
  if (alertQ.isLoading) {
    return (
      <div className="flex justify-center py-16 text-slate-400">
        <Spinner />
      </div>
    );
  }
  if (alertQ.isError || !alertQ.data) {
    return (
      <ErrorState
        title="Failed to load alert"
        description={
          alertQ.error instanceof ApiError
            ? `(${alertQ.error.status})`
            : String(alertQ.error)
        }
      />
    );
  }

  const alert = alertQ.data;
  const detectionDecision =
    alert.decisions.find((d) => d.agent === "DETECTION") ?? null;
  const triageDecision =
    alert.decisions.find((d) => d.agent === "TRIAGE") ?? null;
  const packet = investigationQ.data?.packet ?? null;

  return (
    <section className="space-y-6">
      {/* ---- Header ---- */}
      <div>
        <Link
          to="/alerts"
          className="text-xs text-slate-400 hover:text-slate-200"
        >
          ← Back to alerts
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-2xl font-semibold text-slate-100">
              Alert #{alert.id}{" "}
              <span className="ml-2 text-base font-normal text-slate-400">
                · {alert.prediction}
              </span>
            </h2>
            <p className="mt-1 text-sm text-slate-400">
              <span className="font-mono">{alert.src_ip}</span>
              {alert.src_port ? `:${alert.src_port}` : ""}
              <span className="mx-2 text-slate-600">→</span>
              <span className="font-mono">{alert.dst_ip}</span>
              {alert.dst_port ? `:${alert.dst_port}` : ""}
              {alert.protocol ? ` · ${alert.protocol}` : ""}
              <span className="ml-3 text-slate-500">
                created {formatDateTime(alert.created_at)}
              </span>
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <SeverityPill severity={alert.severity} />
            <StatusPill status={alert.status} />
            <DispositionPill disposition={alert.disposition} />
          </div>
        </div>
      </div>

      {/* ---- Action bar ---- */}
      <AlertActionBar alert={alert} />

      {/* ---- Detection + Triage ---- */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DetectionCard
          decision={detectionDecision}
          fallbackConfidence={alert.confidence}
          fallbackPrediction={alert.prediction}
        />
        <TriageCard alert={alert} decision={triageDecision} />
      </div>

      {/* ---- Investigation summary ---- */}
      <InvestigationCard packet={packet} />

      {/* ---- Response recommendations ---- */}
      <ResponseActionsTable alertId={alert.id} actions={alert.actions} />

      {/* ---- Related evidence ---- */}
      <RelatedEvidence packet={packet} />

      {/* ---- Metadata + decision chain ---- */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-1">
          <AlertOverviewCard alert={alert} />
        </div>
        <div className="lg:col-span-2">
          <DecisionChainCard decisions={alert.decisions} />
        </div>
      </div>
    </section>
  );
}
