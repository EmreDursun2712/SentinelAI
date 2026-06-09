import { useQuery } from "@tanstack/react-query";

import { RefreshIcon } from "@/components/icons";
import { ModelVersionsPanel } from "@/components/models/ModelVersionsPanel";
import { TasksPanel } from "@/components/tasks/TasksPanel";
import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { API_ROOT, healthApi } from "@/lib/api";
import type { DependencyCheck } from "@/lib/types";

function toneFor(check?: DependencyCheck): BadgeTone {
  switch (check?.status) {
    case "ok":
    case "loaded":
      return "success";
    case "skipped":
      return "neutral";
    case "unavailable":
      return "warning";
    case "down":
      return "danger";
    default:
      return "neutral";
  }
}

interface DepCardProps {
  title: string;
  check?: DependencyCheck;
  detail?: string;
}

function DepCard({ title, check, detail }: DepCardProps) {
  return (
    <Card>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        <Badge tone={toneFor(check)}>{check?.status ?? "…"}</Badge>
      </div>
      <dl className="mt-3 space-y-1 text-xs text-slate-400">
        <div className="flex justify-between gap-3">
          <dt>Required</dt>
          <dd className="text-slate-300">{check?.required ? "yes" : "no"}</dd>
        </div>
        {detail && (
          <div className="flex justify-between gap-3">
            <dt>Detail</dt>
            <dd className="text-slate-300">{detail}</dd>
          </div>
        )}
      </dl>
    </Card>
  );
}

export default function SystemPage() {
  const healthQ = useQuery({
    queryKey: ["system", "health"],
    queryFn: healthApi.health,
    refetchInterval: 15_000,
  });
  const readyQ = useQuery({
    queryKey: ["system", "readyz"],
    queryFn: healthApi.readyz,
    refetchInterval: 15_000,
  });

  const checks = readyQ.data?.checks;
  const ready = readyQ.data?.status === "ready";
  const model = checks?.model;
  const redis = checks?.redis;
  const queue = checks?.queue;

  const refresh = () => {
    healthQ.refetch();
    readyQ.refetch();
  };

  return (
    <div>
      <PageHeader
        title="System"
        description="Live health of the backend and its dependencies."
        actions={
          <Button variant="secondary" size="sm" onClick={refresh}>
            <RefreshIcon className="h-4 w-4" />
            Refresh
          </Button>
        }
      />

      {readyQ.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Spinner className="h-4 w-4" /> Checking dependencies…
        </div>
      ) : (
        <>
          <Card className="mb-4 flex items-center justify-between" padding="md">
            <div>
              <p className="text-xs uppercase tracking-wider text-slate-500">Overall readiness</p>
              <p className="mt-0.5 text-lg font-semibold text-slate-100">
                {readyQ.isError ? "unreachable" : ready ? "Ready" : "Not ready"}
              </p>
            </div>
            <Badge tone={readyQ.isError ? "danger" : ready ? "success" : "warning"}>
              {readyQ.isError ? "error" : (readyQ.data?.status ?? "…")}
            </Badge>
          </Card>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <DepCard title="Database" check={checks?.database} />
            <DepCard
              title="Redis (rate limiter)"
              check={redis}
              detail={redis?.backend ? `backend: ${redis.backend}` : undefined}
            />
            <DepCard
              title="Task queue (worker)"
              check={queue}
              detail={queue?.backend ? `backend: ${queue.backend}` : undefined}
            />
            <DepCard
              title="Detection model"
              check={model}
              detail={
                model?.name ? `${model.name} @ ${model.version ?? "?"}` : "no model staged"
              }
            />
          </div>

          <div className="mt-4">
            <ModelVersionsPanel />
          </div>

          <div className="mt-4">
            <TasksPanel />
          </div>

          <Card className="mt-4" padding="md">
            <h3 className="text-sm font-semibold text-slate-200">Observability</h3>
            <p className="mt-2 text-xs leading-relaxed text-slate-400">
              Backend version{" "}
              <span className="font-mono text-slate-300">{healthQ.data?.version ?? "…"}</span>.
              Prometheus metrics (HTTP, ingestion, detection, response, drift, WebSocket
              connections) are exposed for scraping at{" "}
              <a
                href={`${API_ROOT}/metrics`}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-emerald-400 hover:underline"
              >
                /metrics
              </a>
              . Liveness is at <span className="font-mono text-slate-300">/health</span>,
              readiness (this page) at{" "}
              <span className="font-mono text-slate-300">/readyz</span>.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
