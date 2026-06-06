import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { DispositionPill } from "@/components/DispositionPill";
import { SearchIcon } from "@/components/icons";
import { SeverityPill } from "@/components/SeverityPill";
import { StatusPill } from "@/components/StatusPill";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { alertsApi, dashboardApi } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type {
  AlertDisposition,
  AlertStatus,
  Severity,
} from "@/lib/types";

type Sort = "created_at" | "priority" | "severity";

const PAGE_SIZE = 25;
const DEBOUNCE_MS = 300;

export default function AlertsPage() {
  const [params, setParams] = useSearchParams();

  const q = params.get("q") ?? "";
  const severity = (params.get("severity") || "") as Severity | "";
  const status = (params.get("status") || "") as AlertStatus | "";
  const disposition = (params.get("disposition") || "") as AlertDisposition | "";
  const prediction = params.get("prediction") ?? "";
  const sort = (params.get("sort") || "created_at") as Sort;
  const page = Math.max(parseInt(params.get("page") || "1", 10) || 1, 1);

  // Search input is local + debounced so we don't fire a request per keystroke.
  const [searchInput, setSearchInput] = useState(q);
  useEffect(() => {
    if (searchInput === q) return;
    const t = window.setTimeout(() => {
      updateFilter("q", searchInput);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  function clearAllFilters() {
    setSearchInput("");
    setParams(new URLSearchParams(), { replace: true });
  }

  const goToPage = (n: number) => updateFilter("page", String(Math.max(n, 1)));

  // ---- queries ----

  // Stats are cheap; we use them to source the attack-type dropdown options.
  const statsQ = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: dashboardApi.getOverview,
    refetchInterval: 60_000,
  });

  // Fetch PAGE_SIZE+1 so we can tell whether there's a "next page" without
  // an extra count query.
  const offset = (page - 1) * PAGE_SIZE;
  const listQ = useQuery({
    queryKey: [
      "alerts",
      { q, severity, status, disposition, prediction, sort, page },
    ],
    queryFn: () =>
      alertsApi.listAlerts({
        q: q || undefined,
        severity: severity || undefined,
        status: status || undefined,
        disposition: disposition || undefined,
        prediction: prediction || undefined,
        sort,
        limit: PAGE_SIZE + 1,
        offset,
      }),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  const rows = useMemo(() => (listQ.data ?? []).slice(0, PAGE_SIZE), [listQ.data]);
  const hasNext = (listQ.data ?? []).length > PAGE_SIZE;
  const hasPrev = page > 1;

  const activeFilterCount = [q, severity, status, disposition, prediction].filter(
    Boolean,
  ).length;

  const predictionOptions = useMemo(() => {
    const map = statsQ.data?.alerts.by_prediction ?? {};
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }));
  }, [statsQ.data]);

  return (
    <section className="space-y-5">
      <PageHeader
        title="Alerts"
        description={
          activeFilterCount > 0
            ? `${activeFilterCount} active filter(s) · ${rows.length} row(s) on page ${page}.`
            : "Search and filter alerts across severity, status, disposition, and attack family."
        }
      />

      {/* ---- Filter bar ---- */}
      <Card padding="sm">
        <div className="flex flex-wrap items-end gap-3 px-2 py-2">
          {/* Search */}
          <label className="inline-flex min-w-[220px] flex-col gap-1 text-xs text-slate-400">
            <span className="font-medium uppercase tracking-wider">Search</span>
            <span className="relative">
              <SearchIcon className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="IP or attack family"
                className="w-full rounded-md border border-slate-700 bg-slate-900/60 py-1.5 pl-8 pr-2.5 text-sm text-slate-200 placeholder-slate-500 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </span>
          </label>

          <Select
            label="Severity"
            value={severity}
            onChange={(e) => updateFilter("severity", e.target.value)}
          >
            <option value="">Any</option>
            <option value="CRITICAL">Critical</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </Select>

          <Select
            label="Status"
            value={status}
            onChange={(e) => updateFilter("status", e.target.value)}
          >
            <option value="">Any</option>
            <option value="NEW">NEW</option>
            <option value="TRIAGED">TRIAGED</option>
            <option value="AUTO_RESPONDED">AUTO_RESPONDED</option>
            <option value="AWAITING_ANALYST">AWAITING_ANALYST</option>
            <option value="INVESTIGATED">INVESTIGATED</option>
            <option value="REPORTED">REPORTED</option>
            <option value="CLOSED">CLOSED</option>
          </Select>

          <Select
            label="Disposition"
            value={disposition}
            onChange={(e) => updateFilter("disposition", e.target.value)}
          >
            <option value="">Any</option>
            <option value="OPEN">OPEN</option>
            <option value="UNDER_REVIEW">UNDER_REVIEW</option>
            <option value="CONFIRMED">CONFIRMED</option>
            <option value="FALSE_POSITIVE">FALSE_POSITIVE</option>
            <option value="RESOLVED">RESOLVED</option>
          </Select>

          <Select
            label="Attack type"
            value={prediction}
            onChange={(e) => updateFilter("prediction", e.target.value)}
          >
            <option value="">Any</option>
            {predictionOptions.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name} ({p.count})
              </option>
            ))}
          </Select>

          <Select
            label="Sort by"
            value={sort}
            onChange={(e) => updateFilter("sort", e.target.value)}
          >
            <option value="created_at">Newest first</option>
            <option value="priority">Priority (high → low)</option>
            <option value="severity">Severity (high → low)</option>
          </Select>

          {activeFilterCount > 0 && (
            <Button variant="ghost" onClick={clearAllFilters}>
              Clear filters
            </Button>
          )}
        </div>
      </Card>

      {/* ---- Results table ---- */}
      <Card padding="none">
        {listQ.isLoading ? (
          <div className="flex justify-center p-12 text-slate-400">
            <Spinner />
          </div>
        ) : listQ.isError ? (
          <ErrorState
            title="Failed to load alerts"
            description="Check that the backend is reachable from the browser."
          />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No alerts match the current filter"
            description={
              activeFilterCount > 0
                ? "Try widening the filter, or clear it entirely."
                : "Ingest a CSV and run detection to populate this view."
            }
            action={
              activeFilterCount > 0 ? (
                <Button variant="secondary" onClick={clearAllFilters}>
                  Clear filters
                </Button>
              ) : (
                <Link
                  to="/ingestion"
                  className="text-sm text-emerald-400 hover:underline"
                >
                  Go to Ingestion →
                </Link>
              )
            }
          />
        ) : (
          <>
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>Severity</Th>
                  <Th>Prediction</Th>
                  <Th>Source</Th>
                  <Th>Target</Th>
                  <Th className="text-right">Conf.</Th>
                  <Th className="text-right">Priority</Th>
                  <Th>Status</Th>
                  <Th>Disposition</Th>
                  <Th>Age</Th>
                </Tr>
              </Thead>
              <Tbody>
                {rows.map((a) => (
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
                    <Td className="font-mono text-xs text-slate-400">
                      {a.src_ip}
                      {a.src_port ? `:${a.src_port}` : ""}
                    </Td>
                    <Td className="font-mono text-xs text-slate-400">
                      {a.dst_ip}
                      {a.dst_port ? `:${a.dst_port}` : ""}
                    </Td>
                    <Td className="text-right font-mono text-slate-300">
                      {a.confidence.toFixed(2)}
                    </Td>
                    <Td className="text-right font-mono text-slate-300">
                      {a.priority?.toFixed(1) ?? "—"}
                    </Td>
                    <Td>
                      <StatusPill status={a.status} />
                    </Td>
                    <Td>
                      <DispositionPill disposition={a.disposition} />
                    </Td>
                    <Td className="text-xs text-slate-500">
                      {formatRelative(a.created_at)}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>

            {/* ---- Pagination ---- */}
            <div className="flex items-center justify-between border-t border-slate-800 px-5 py-3 text-xs text-slate-400">
              <span>
                Page <span className="text-slate-300">{page}</span>
                <span className="mx-1 text-slate-600">·</span>
                Showing{" "}
                <span className="text-slate-300">{rows.length}</span> row(s)
                {listQ.isFetching && (
                  <span className="ml-2 inline-flex items-center gap-1 text-slate-500">
                    <Spinner className="h-3 w-3" />
                    refreshing
                  </span>
                )}
              </span>
              <div className="flex items-center gap-2">
                {activeFilterCount > 0 && (
                  <Badge tone="neutral">{activeFilterCount} filter(s)</Badge>
                )}
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!hasPrev || listQ.isFetching}
                  onClick={() => goToPage(page - 1)}
                >
                  ← Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!hasNext || listQ.isFetching}
                  onClick={() => goToPage(page + 1)}
                >
                  Next →
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}
