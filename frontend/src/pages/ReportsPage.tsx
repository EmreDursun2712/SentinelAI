import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { MarkdownView } from "@/components/MarkdownView";
import { SeverityPill } from "@/components/SeverityPill";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { alertsApi, reportsApi } from "@/lib/api";
import { formatDateTime, formatRelative } from "@/lib/format";

const ALREADY_REPORTED = new Set(["REPORTED", "CLOSED"]);

export default function ReportsPage() {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const listQ = useQuery({
    queryKey: ["reports"],
    queryFn: () => reportsApi.listReports({ limit: 50 }),
    refetchInterval: 60_000,
  });

  const detailQ = useQuery({
    queryKey: ["reports", selectedId],
    queryFn: () => reportsApi.getReport(selectedId!),
    enabled: selectedId != null,
  });

  // Alerts not yet reported (and not closed) — eligible for one-click report.
  const pendingAlertsQ = useQuery({
    queryKey: ["alerts", "needs-report"],
    queryFn: () => alertsApi.listAlerts({ sort: "priority", limit: 50 }),
    refetchInterval: 60_000,
  });

  const dailyMut = useMutation({
    mutationFn: () => reportsApi.runDailySummary(),
    onSuccess: (out) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      setSelectedId(out.report_id);
    },
  });

  const generateForAlert = useMutation({
    mutationFn: (alertId: number) => alertsApi.generateAlertReport(alertId),
    onSuccess: (envelope) => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["alerts", "needs-report"] });
      setSelectedId(envelope.report_id);
    },
  });

  const pendingAlerts = useMemo(
    () => (pendingAlertsQ.data?.items ?? []).filter((a) => !ALREADY_REPORTED.has(a.status)),
    [pendingAlertsQ.data],
  );

  const last24hCount = useMemo(() => {
    const since = Date.now() - 24 * 60 * 60 * 1000;
    return (listQ.data ?? []).filter((r) => Date.parse(r.created_at) >= since)
      .length;
  }, [listQ.data]);

  const markdown = String(detailQ.data?.packet?.markdown ?? "");

  return (
    <section className="space-y-6">
      <PageHeader
        title="Reports"
        description={`${listQ.data?.length ?? 0} total · ${last24hCount} created in the last 24h`}
        actions={
          <Button
            variant="primary"
            onClick={() => dailyMut.mutate()}
            disabled={dailyMut.isPending}
          >
            {dailyMut.isPending && <Spinner className="h-3 w-3" />}
            Generate daily summary
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* ---------- left rail ---------- */}
        <div className="space-y-4">
          {/* Pending alerts — one-click generate */}
          <Card padding="none">
            <div className="border-b border-slate-800 px-5 py-3">
              <CardTitle>Alerts without a report</CardTitle>
              <p className="text-xs text-slate-500">
                Top {pendingAlerts.length} by priority. One click to generate.
              </p>
            </div>
            {pendingAlertsQ.isLoading ? (
              <div className="flex justify-center p-6 text-slate-400">
                <Spinner />
              </div>
            ) : pendingAlerts.length === 0 ? (
              <EmptyState
                title="Every alert is reported"
                description="No open or in-progress alerts to report on."
              />
            ) : (
              <ul className="max-h-72 divide-y divide-slate-800/70 overflow-y-auto">
                {pendingAlerts.slice(0, 8).map((a) => (
                  <li
                    key={a.id}
                    className="flex items-center gap-2 px-4 py-2.5 text-sm"
                  >
                    <SeverityPill severity={a.severity} />
                    <div className="min-w-0 flex-1">
                      <Link
                        to={`/alerts/${a.id}`}
                        className="font-mono text-emerald-400 hover:underline"
                      >
                        #{a.id}
                      </Link>
                      <span className="ml-1 truncate text-slate-300">
                        · {a.prediction}
                      </span>
                      <div className="text-[11px] text-slate-500">
                        {a.status} · prio {a.priority?.toFixed(1) ?? "—"}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={
                        generateForAlert.isPending &&
                        generateForAlert.variables === a.id
                      }
                      onClick={() => generateForAlert.mutate(a.id)}
                    >
                      {generateForAlert.isPending &&
                        generateForAlert.variables === a.id && (
                          <Spinner className="h-3 w-3" />
                        )}
                      Generate
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* All reports */}
          <Card padding="none">
            <div className="border-b border-slate-800 px-5 py-3">
              <CardTitle>All reports</CardTitle>
              <p className="text-xs text-slate-500">
                {listQ.data?.length ?? 0} total
              </p>
            </div>
            {listQ.isLoading ? (
              <div className="flex justify-center p-6 text-slate-400">
                <Spinner />
              </div>
            ) : listQ.isError ? (
              <ErrorState description="Failed to load reports." />
            ) : listQ.data?.length === 0 ? (
              <EmptyState
                title="No reports yet"
                description="Generate one from above, or run today's daily summary."
              />
            ) : (
              <ul className="max-h-[60vh] divide-y divide-slate-800/70 overflow-y-auto">
                {listQ.data!.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(r.id)}
                      className={`flex w-full flex-col gap-1 px-5 py-3 text-left transition hover:bg-slate-800/50 ${
                        selectedId === r.id
                          ? "bg-slate-800/70 ring-1 ring-inset ring-slate-700"
                          : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium text-slate-200">
                          {r.title}
                        </span>
                        <Badge tone={r.kind === "PER_ALERT" ? "info" : "indigo"}>
                          {r.kind}
                        </Badge>
                      </div>
                      <div className="flex items-center justify-between text-xs text-slate-500">
                        <span className="font-mono">#{r.id}</span>
                        <span>{formatRelative(r.created_at)}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        {/* ---------- viewer ---------- */}
        <div className="lg:col-span-2">
          <Card padding="none">
            <ReportViewer
              isSelected={selectedId != null}
              isLoading={detailQ.isLoading && selectedId != null}
              isError={detailQ.isError}
              title={detailQ.data?.title}
              kind={detailQ.data?.kind}
              alertId={detailQ.data?.alert_id ?? null}
              createdAt={detailQ.data?.created_at}
              mdPath={detailQ.data?.md_path ?? null}
              markdown={markdown}
              reportId={selectedId}
            />
          </Card>
        </div>
      </div>
    </section>
  );
}

// ---------- viewer ----------

interface ReportViewerProps {
  isSelected: boolean;
  isLoading: boolean;
  isError: boolean;
  title?: string;
  kind?: string;
  alertId: number | null;
  createdAt?: string;
  mdPath: string | null;
  markdown: string;
  reportId: number | null;
}

function ReportViewer(p: ReportViewerProps) {
  const [copied, setCopied] = useState(false);

  if (!p.isSelected) {
    return (
      <EmptyState
        title="No report selected"
        description="Pick one from the list, or generate a new report from an alert on the left."
      />
    );
  }
  if (p.isLoading) {
    return (
      <div className="flex justify-center p-12 text-slate-400">
        <Spinner />
      </div>
    );
  }
  if (p.isError) {
    return <ErrorState description="Failed to load this report." />;
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(p.markdown);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const handleDownload = () => {
    const blob = new Blob([p.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `report-${p.reportId ?? "unknown"}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <div className="border-b border-slate-800 px-6 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-100">
              {p.title ?? `Report #${p.reportId}`}
            </h3>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              {p.kind && (
                <Badge tone={p.kind === "PER_ALERT" ? "info" : "indigo"}>
                  {p.kind}
                </Badge>
              )}
              {p.alertId != null && (
                <Link
                  to={`/alerts/${p.alertId}`}
                  className="text-emerald-400 hover:underline"
                >
                  Linked alert #{p.alertId} →
                </Link>
              )}
              <span>· Generated {formatDateTime(p.createdAt)}</span>
              {p.mdPath && (
                <span className="font-mono text-slate-500">· {p.mdPath}</span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="secondary" size="sm" onClick={handleCopy}>
              {copied ? "Copied" : "Copy markdown"}
            </Button>
            <Button variant="primary" size="sm" onClick={handleDownload}>
              Download .md
            </Button>
          </div>
        </div>
      </div>

      <div className="max-h-[72vh] overflow-y-auto px-6 py-5">
        {p.markdown ? (
          <MarkdownView source={p.markdown} />
        ) : (
          <EmptyState title="This report has no markdown body." />
        )}
      </div>
    </div>
  );
}
