import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { dashboardApi, responseApi } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { ResponseActionOut, ResponseActionType, ResponseStatus } from "@/lib/types";

const ANALYST_ID = "ui-analyst";

const ACTION_TYPES: ResponseActionType[] = [
  "BLOCK_IP",
  "RATE_LIMIT",
  "ISOLATE_HOST",
  "ISOLATE_ALERT",
  "SUPPRESS_ALERT",
  "ESCALATE",
  "NOTIFY_ANALYST",
  "CREATE_TICKET",
  "NO_ACTION",
];

function isToday(iso: string): boolean {
  const since = Date.now() - 24 * 60 * 60 * 1000;
  return Date.parse(iso) >= since;
}

function statusTone(s: ResponseStatus): "info" | "success" | "warning" | "neutral" {
  if (s === "EXECUTED") return "success";
  if (s === "REJECTED") return "neutral";
  if (s === "PENDING") return "warning";
  return "info";
}

export default function ResponseCenterPage() {
  const qc = useQueryClient();
  const [actionFilter, setActionFilter] = useState<ResponseActionType | "">("");

  const overviewQ = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: dashboardApi.getOverview,
    refetchInterval: 30_000,
  });

  const pendingQ = useQuery({
    queryKey: ["response", "pending", actionFilter],
    queryFn: () =>
      responseApi.listResponseActions({
        status: "PENDING",
        action_type: actionFilter || undefined,
        limit: 100,
      }),
    refetchInterval: 10_000,
  });

  const recentQ = useQuery({
    queryKey: ["response", "recent", actionFilter],
    queryFn: () =>
      responseApi.listResponseActions({
        action_type: actionFilter || undefined,
        limit: 50,
      }),
    refetchInterval: 30_000,
  });

  const approve = useMutation({
    mutationFn: (id: number) =>
      responseApi.approveResponseAction(id, { analyst_id: ANALYST_ID }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["response"] });
      qc.invalidateQueries({ queryKey: ["alert"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      responseApi.rejectResponseAction(id, {
        analyst_id: ANALYST_ID,
        reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["response"] });
      qc.invalidateQueries({ queryKey: ["alert"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  // Last-24h derived counts from the recent feed.
  const stats = useMemo(() => {
    const recent = recentQ.data ?? [];
    let autoToday = 0;
    let approvedToday = 0;
    let rejectedToday = 0;
    for (const a of recent) {
      if (!isToday(a.created_at)) continue;
      if (a.status === "EXECUTED" && !a.approval_required) autoToday++;
      else if (a.status === "EXECUTED" && a.approval_required) approvedToday++;
      else if (a.status === "REJECTED") rejectedToday++;
    }
    return { autoToday, approvedToday, rejectedToday };
  }, [recentQ.data]);

  const pendingCount = overviewQ.data?.pending_actions ?? pendingQ.data?.length ?? 0;

  return (
    <section className="space-y-6">
      <PageHeader
        title="Response Center"
        description="Pending recommendations awaiting analyst approval. Every action is simulated only."
      />

      {/* KPI cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Pending"
          value={overviewQ.isLoading ? "…" : pendingCount}
          tone={pendingCount > 0 ? "warning" : "default"}
          hint="Awaiting analyst decision"
        />
        <StatCard
          label="Auto-executed · 24h"
          value={recentQ.isLoading ? "…" : stats.autoToday}
          hint="Notifications, tickets, auto-blocks"
        />
        <StatCard
          label="Approved · 24h"
          value={recentQ.isLoading ? "…" : stats.approvedToday}
          tone={stats.approvedToday > 0 ? "success" : "default"}
          hint="Approve-then-execute path"
        />
        <StatCard
          label="Rejected · 24h"
          value={recentQ.isLoading ? "…" : stats.rejectedToday}
          tone={stats.rejectedToday > 0 ? "danger" : "default"}
          hint="With a written reason"
        />
      </div>

      {/* Filter row */}
      <Card padding="sm">
        <div className="flex flex-wrap items-end gap-3 px-2 py-2">
          <Select
            label="Action type"
            value={actionFilter}
            onChange={(e) =>
              setActionFilter(e.target.value as ResponseActionType | "")
            }
          >
            <option value="">Any</option>
            {ACTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
          {actionFilter && (
            <Button variant="ghost" onClick={() => setActionFilter("")}>
              Clear
            </Button>
          )}
          <div className="ml-auto text-xs text-slate-500">
            {pendingQ.isFetching && (
              <span className="inline-flex items-center gap-1">
                <Spinner className="h-3 w-3" /> refreshing
              </span>
            )}
          </div>
        </div>
      </Card>

      {/* Pending queue */}
      <Card padding="none">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              Pending queue
            </h3>
            <p className="text-xs text-slate-500">
              {pendingQ.data?.length ?? 0} action(s) awaiting decision
              {actionFilter && ` · filtered to ${actionFilter}`}.
            </p>
          </div>
        </div>

        {pendingQ.isLoading ? (
          <div className="flex justify-center p-10 text-slate-400">
            <Spinner />
          </div>
        ) : pendingQ.isError ? (
          <ErrorState description="Failed to load pending actions." />
        ) : pendingQ.data?.length === 0 ? (
          <EmptyState
            title="No pending actions"
            description="High-severity recommendations auto-executed; the rest were already resolved."
          />
        ) : (
          <ul className="divide-y divide-slate-800/70">
            {pendingQ.data!.map((a) => (
              <PendingActionRow
                key={a.id}
                action={a}
                isApproving={approve.isPending && approve.variables === a.id}
                isRejecting={reject.isPending && reject.variables?.id === a.id}
                onApprove={() => approve.mutate(a.id)}
                onReject={(reason) => reject.mutate({ id: a.id, reason })}
              />
            ))}
          </ul>
        )}
      </Card>

      {/* Recent activity */}
      <Card padding="none">
        <div className="border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Simulated action execution history
          </h3>
          <p className="text-xs text-slate-500">
            Last 50 response actions across every alert.
          </p>
        </div>

        {recentQ.isLoading ? (
          <div className="flex justify-center p-8 text-slate-400">
            <Spinner />
          </div>
        ) : recentQ.data?.length === 0 ? (
          <EmptyState title="No response activity yet" />
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>#</Th>
                <Th>Alert</Th>
                <Th>Action</Th>
                <Th>Approval</Th>
                <Th>Status</Th>
                <Th>Decided by</Th>
                <Th>Executed</Th>
                <Th>Age</Th>
              </Tr>
            </Thead>
            <Tbody>
              {recentQ.data?.map((a) => (
                <Tr key={a.id}>
                  <Td className="font-mono text-slate-500">{a.id}</Td>
                  <Td>
                    <Link
                      to={`/alerts/${a.alert_id}`}
                      className="font-mono text-emerald-400 hover:underline"
                    >
                      #{a.alert_id}
                    </Link>
                  </Td>
                  <Td>
                    <Badge tone="default">{a.action_type}</Badge>
                  </Td>
                  <Td className="text-xs text-slate-400">
                    {a.approval_required ? "analyst" : "auto"}
                  </Td>
                  <Td>
                    <Badge tone={statusTone(a.status)}>{a.status}</Badge>
                  </Td>
                  <Td className="font-mono text-xs text-slate-400">
                    {a.approved_by ?? (a.executed && !a.approval_required ? "auto" : "—")}
                  </Td>
                  <Td className="text-xs text-slate-400">
                    {a.executed_at ? formatRelative(a.executed_at) : "—"}
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
    </section>
  );
}

// ---------- pending row with visible rationale + payload toggle ----------

interface PendingRowProps {
  action: ResponseActionOut;
  isApproving: boolean;
  isRejecting: boolean;
  onApprove: () => void;
  onReject: (reason: string) => void;
}

function PendingActionRow({
  action,
  isApproving,
  isRejecting,
  onApprove,
  onReject,
}: PendingRowProps) {
  const [open, setOpen] = useState(false);
  const rationale =
    (action.payload?.rationale as string | undefined) ?? "No rationale provided.";

  // Strip rationale + low-signal fields so the payload block focuses on what
  // the analyst still hasn't seen.
  const extraPayload = useMemo(() => {
    const { rationale: _r, ...rest } = action.payload ?? {};
    return rest;
  }, [action.payload]);

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="default">{action.action_type}</Badge>
            <Link
              to={`/alerts/${action.alert_id}`}
              className="font-mono text-xs text-emerald-400 hover:underline"
            >
              alert #{action.alert_id}
            </Link>
            <span className="text-xs text-slate-500">
              · created {formatRelative(action.created_at)}
            </span>
          </div>
          <p className="mt-2 text-sm text-slate-300">{rationale}</p>
          {Object.keys(extraPayload).length > 0 && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              className="mt-2 text-xs text-slate-400 hover:text-slate-200"
            >
              {open ? "Hide payload" : "Show payload"}
            </button>
          )}
          {open && (
            <pre className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded border border-slate-800 bg-slate-950/60 p-2 text-[11px] font-mono text-slate-300">
              {JSON.stringify(extraPayload, null, 2)}
            </pre>
          )}
        </div>

        <div className="flex shrink-0 gap-2">
          <Button
            variant="primary"
            size="sm"
            disabled={isApproving || isRejecting}
            onClick={onApprove}
          >
            {isApproving && <Spinner className="h-3 w-3" />}
            Approve
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={isApproving || isRejecting}
            onClick={() => {
              const reason = window.prompt("Reason for rejection?", "");
              if (reason && reason.trim()) onReject(reason.trim());
            }}
          >
            {isRejecting && <Spinner className="h-3 w-3" />}
            Reject
          </Button>
        </div>
      </div>
    </li>
  );
}
