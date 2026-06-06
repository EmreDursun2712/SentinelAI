import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ModelHealthPanel } from "@/components/dashboard/ModelHealthPanel";
import { AlertsOverTimeChart } from "@/components/charts/AlertsOverTimeChart";
import { SeverityDistributionChart } from "@/components/charts/SeverityDistributionChart";
import { TopPredictionsChart } from "@/components/charts/TopPredictionsChart";
import { SeverityPill } from "@/components/SeverityPill";
import { StatCard } from "@/components/StatCard";
import { StatusPill } from "@/components/StatusPill";
import { ArrowRightIcon, IngestionIcon, PlayIcon } from "@/components/icons";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { alertsApi, dashboardApi, detectionApi } from "@/lib/api";
import { useLiveInterval } from "@/lib/stream/StreamProvider";
import { formatRelative } from "@/lib/format";

const TIMESERIES_HOURS = 24;

export default function DashboardPage() {
  const overviewQ = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: dashboardApi.getOverview,
    refetchInterval: useLiveInterval(15_000),
  });
  const timeseriesQ = useQuery({
    queryKey: ["alerts", "timeseries", TIMESERIES_HOURS],
    queryFn: () => alertsApi.getAlertTimeseries(TIMESERIES_HOURS),
    refetchInterval: useLiveInterval(30_000),
  });
  const recentQ = useQuery({
    queryKey: ["alerts", "recent"],
    queryFn: () => alertsApi.listAlerts({ sort: "priority", limit: 10 }),
    refetchInterval: useLiveInterval(30_000),
  });
  const modelQ = useQuery({
    queryKey: ["detection", "model"],
    queryFn: detectionApi.getModelInfo,
  });

  const ov = overviewQ.data;
  const loading = overviewQ.isLoading;

  const isEmpty =
    !loading && (ov?.total_events ?? 0) === 0 && (ov?.alerts.total ?? 0) === 0;

  return (
    <section className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Live SOC overview. Detections, triage, response, and reporting at a glance."
      />

      {isEmpty && <FirstRunBanner />}

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total events"
          value={loading ? "…" : (ov?.total_events ?? 0).toLocaleString()}
          hint="Network flow records ingested"
        />
        <StatCard
          label="Suspicious events"
          value={loading ? "…" : (ov?.suspicious_events ?? 0).toLocaleString()}
          hint={
            ov && ov.total_events > 0
              ? `${((ov.suspicious_events / ov.total_events) * 100).toFixed(1)}% of total events`
              : "0% of total events"
          }
        />
        <StatCard
          label="Open alerts"
          value={loading ? "…" : (ov?.open_alerts ?? 0).toLocaleString()}
          tone={ov && ov.open_alerts > 0 ? "warning" : "default"}
          hint={`${ov?.pending_actions ?? 0} response action(s) awaiting approval`}
        />
        <StatCard
          label="Critical alerts"
          value={loading ? "…" : (ov?.critical_alerts ?? 0).toLocaleString()}
          tone={ov && ov.critical_alerts > 0 ? "danger" : "default"}
          hint={`+${ov?.high_alerts ?? 0} HIGH severity`}
        />
      </div>

      {/* Model health / drift monitoring */}
      <ModelHealthPanel />

      {/* Charts row 1: stacked area (wide) */}
      <Card padding="md">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              Alerts over time
            </h3>
            <p className="text-xs text-slate-500">
              Last {TIMESERIES_HOURS} hours, stacked by severity. Bucketed hourly.
            </p>
          </div>
        </div>
        {timeseriesQ.isLoading ? (
          <ChartLoading />
        ) : timeseriesQ.isError ? (
          <ErrorState description="Failed to load alert timeseries." />
        ) : (
          <AlertsOverTimeChart points={timeseriesQ.data?.points ?? []} />
        )}
      </Card>

      {/* Charts row 2: severity donut + top predictions side by side */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card padding="md">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-200">
              Severity distribution
            </h3>
            <p className="text-xs text-slate-500">
              All alerts on record.
            </p>
          </div>
          {overviewQ.isLoading ? (
            <ChartLoading />
          ) : overviewQ.isError ? (
            <ErrorState description="Failed to load alert stats." />
          ) : (
            <SeverityDistributionChart
              bySeverity={ov?.alerts.by_severity ?? {}}
            />
          )}
        </Card>

        <Card padding="md">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-200">
              Top attack categories
            </h3>
            <p className="text-xs text-slate-500">
              Predicted attack family counts.
            </p>
          </div>
          {overviewQ.isLoading ? (
            <ChartLoading />
          ) : overviewQ.isError ? (
            <ErrorState description="Failed to load attack categories." />
          ) : (
            <TopPredictionsChart
              byPrediction={ov?.alerts.by_prediction ?? {}}
            />
          )}
        </Card>
      </div>

      {/* Recent alerts + side panel */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card padding="none" className="xl:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">
                Highest-priority alerts
              </h3>
              <p className="text-xs text-slate-500">
                Sorted by priority. Updates every 30s.
              </p>
            </div>
            <Link
              to="/alerts?sort=priority"
              className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300"
            >
              View all
              <ArrowRightIcon className="h-3.5 w-3.5" />
            </Link>
          </div>
          {recentQ.isLoading ? (
            <div className="flex justify-center p-8 text-slate-400">
              <Spinner />
            </div>
          ) : recentQ.isError ? (
            <ErrorState description="Failed to load alerts." />
          ) : recentQ.data?.length === 0 ? (
            <EmptyState
              title="No alerts yet"
              description="Ingest a CSV and run detection to populate this view."
              action={
                <Link to="/ingestion">
                  <Button variant="primary">
                    <PlayIcon className="h-3.5 w-3.5" />
                    Open Ingestion workflow
                  </Button>
                </Link>
              }
            />
          ) : (
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>Severity</Th>
                  <Th>Prediction</Th>
                  <Th>Source → Target</Th>
                  <Th className="text-right">Priority</Th>
                  <Th>Status</Th>
                  <Th>Age</Th>
                </Tr>
              </Thead>
              <Tbody>
                {recentQ.data!.map((a) => (
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
                    <Td className="text-xs text-slate-400">
                      <span className="font-mono">{a.src_ip}</span>
                      <span className="mx-1 text-slate-600">→</span>
                      <span className="font-mono">
                        {a.dst_ip}
                        {a.dst_port ? `:${a.dst_port}` : ""}
                      </span>
                    </Td>
                    <Td className="text-right font-mono text-slate-300">
                      {a.priority?.toFixed(1) ?? "—"}
                    </Td>
                    <Td>
                      <StatusPill status={a.status} />
                    </Td>
                    <Td className="text-xs text-slate-500">
                      {formatRelative(a.created_at)}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Card>

        <Card padding="md">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-200">Model</h3>
            <p className="text-xs text-slate-500">
              The classifier currently serving inference.
            </p>
          </div>
          {modelQ.isLoading ? (
            <ChartLoading />
          ) : !modelQ.data?.loaded ? (
            <EmptyState
              title="No model loaded"
              description="Run `python -m ml.train …` and stage the artifact under ml/artifacts/latest/."
            />
          ) : (
            <dl className="space-y-2 text-xs">
              <ModelRow label="Name" value={modelQ.data.name ?? "—"} mono />
              <ModelRow label="Version" value={modelQ.data.version ?? "—"} mono />
              <ModelRow
                label="Algorithm"
                value={modelQ.data.algorithm ?? "—"}
              />
              <ModelRow
                label="Threshold"
                value={modelQ.data.threshold?.toFixed(2) ?? "—"}
                mono
              />
              <div className="border-t border-slate-800 pt-2">
                <p className="text-slate-400">Classes</p>
                <p className="mt-1 font-mono text-slate-300">
                  {modelQ.data.classes.join(" · ")}
                </p>
              </div>
              <div className="border-t border-slate-800 pt-2 text-slate-500">
                <p>{modelQ.data.feature_order.length} features in input vector</p>
              </div>
            </dl>
          )}
        </Card>
      </div>
    </section>
  );
}

function ChartLoading() {
  return (
    <div className="flex h-[260px] items-center justify-center text-slate-500">
      <Spinner />
    </div>
  );
}

function FirstRunBanner() {
  return (
    <Card
      padding="lg"
      className="border-emerald-500/30 bg-gradient-to-br from-emerald-500/10 via-slate-900/60 to-slate-900/40"
    >
      <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40">
            <IngestionIcon className="h-5 w-5" />
          </span>
          <div>
            <h3 className="text-base font-semibold text-slate-100">
              Welcome to SentinelAI
            </h3>
            <p className="mt-1 max-w-2xl text-sm text-slate-400">
              No events ingested yet. Run the bundled sample on the Ingestion
              page to populate the dashboard — 60 flows covering benign
              browsing, port scans, brute-force, and DDoS, ready in one click.
            </p>
          </div>
        </div>
        <Link to="/ingestion" className="shrink-0">
          <Button variant="primary">
            <PlayIcon className="h-3.5 w-3.5" />
            Start the demo workflow
            <ArrowRightIcon className="h-3.5 w-3.5" />
          </Button>
        </Link>
      </div>
    </Card>
  );
}

function ModelRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className={`text-slate-300 ${mono ? "font-mono" : ""}`}>{value}</dd>
    </div>
  );
}
