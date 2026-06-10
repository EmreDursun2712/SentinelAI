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
import type { ListResult } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { useConfirm } from "@/lib/confirm/ConfirmProvider";
import {
  LAB_APPROVE_WARNING,
  canRollback,
  executionModeLabel,
  executionModeTone,
  isRealLabAction,
} from "@/lib/response";
import { useToast } from "@/lib/toast/ToastContext";
import { useLiveInterval } from "@/lib/stream/StreamProvider";
import { formatRelative } from "@/lib/format";
import type { ResponseActionOut, ResponseActionType, ResponseStatus } from "@/lib/types";

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
  const toast = useToast();
  const confirm = useConfirm();
  const { user } = useAuth();
  const analystId = user?.username;
  const [actionFilter, setActionFilter] = useState<ResponseActionType | "">("");

  const overviewQ = useQuery({
    queryKey: ["dashboard", "overview"],
    queryFn: dashboardApi.getOverview,
    refetchInterval: useLiveInterval(30_000),
  });

  const PENDING_PAGE = 100;
  const pendingQ = useQuery({
    queryKey: ["response", "pending", actionFilter],
    queryFn: () =>
      responseApi.listResponseActionsPage({
        status: "PENDING",
        action_type: actionFilter || undefined,
        limit: PENDING_PAGE,
      }),
    refetchInterval: useLiveInterval(10_000),
  });

  const recentQ = useQuery({
    queryKey: ["response", "recent", actionFilter],
    queryFn: () =>
      responseApi.listResponseActions({
        action_type: actionFilter || undefined,
        limit: 50,
      }),
    refetchInterval: useLiveInterval(30_000),
  });

  // Optimistically drop a decided action from every cached pending list (and
  // decrement its total), with a snapshot so onError can restore server truth.
  const dropFromPending = async (id: number) => {
    await qc.cancelQueries({ queryKey: ["response", "pending"] });
    const snapshots = qc.getQueriesData<ListResult<ResponseActionOut>>({
      queryKey: ["response", "pending"],
    });
    for (const [key, data] of snapshots) {
      if (!data) continue;
      const items = data.items.filter((a) => a.id !== id);
      qc.setQueryData(key, {
        items,
        total: items.length < data.items.length ? Math.max(0, data.total - 1) : data.total,
      });
    }
    return { snapshots };
  };

  const restorePending = (
    ctx:
      | { snapshots?: [readonly unknown[], ListResult<ResponseActionOut> | undefined][] }
      | undefined,
  ) => {
    ctx?.snapshots?.forEach(([key, data]) => qc.setQueryData(key, data));
  };

  const settle = () => {
    qc.invalidateQueries({ queryKey: ["response"] });
    qc.invalidateQueries({ queryKey: ["alert"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };

  const approve = useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) =>
      responseApi.approveResponseAction(id, { analyst_id: analystId, note }),
    onMutate: ({ id }) => dropFromPending(id),
    onError: (err, _v, ctx) => {
      restorePending(ctx);
      toast.error(errorMessage(err, "Could not approve the action."));
    },
    onSuccess: () => toast.success("Response action approved."),
    onSettled: settle,
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      responseApi.rejectResponseAction(id, { analyst_id: analystId, reason }),
    onMutate: ({ id }) => dropFromPending(id),
    onError: (err, _v, ctx) => {
      restorePending(ctx);
      toast.error(errorMessage(err, "Could not reject the action."));
    },
    onSuccess: () => toast.success("Response action rejected."),
    onSettled: settle,
  });

  const rollback = useMutation({
    mutationFn: (id: number) =>
      responseApi.rollbackResponseAction(id, { analyst_id: analystId }),
    onError: (err) => toast.error(errorMessage(err, "Rollback failed.")),
    onSuccess: () => toast.success("Lab action rolled back."),
    onSettled: settle,
  });

  async function handleApprove(action: ResponseActionOut) {
    if (!isRealLabAction(action)) {
      approve.mutate({ id: action.id });
      return;
    }
    const { confirmed, reason } = await confirm({
      title: "Approve real LAB action",
      tone: "danger",
      confirmLabel: "Approve LAB action",
      typedConfirmation: "CONFIRM",
      requireReason: true,
      reasonLabel: "Reason for approval",
      message: (
        <>
          This approves a <strong>real</strong> action against{" "}
          <span className="font-mono">{String(action.payload?.target_ip ?? "the lab")}</span>.{" "}
          {LAB_APPROVE_WARNING}
        </>
      ),
    });
    if (confirmed) approve.mutate({ id: action.id, note: reason });
  }

  async function handleReject(action: ResponseActionOut) {
    const { confirmed, reason } = await confirm({
      title: `Reject action #${action.id}`,
      tone: "danger",
      confirmLabel: "Reject action",
      requireReason: true,
      reasonLabel: "Reason for rejection",
    });
    if (confirmed && reason) reject.mutate({ id: action.id, reason });
  }

  async function handleRollback(action: ResponseActionOut) {
    const { confirmed } = await confirm({
      title: `Roll back lab action #${action.id}`,
      tone: "danger",
      confirmLabel: "Roll back",
      message: `${LAB_APPROVE_WARNING} This reverts the real lab effect.`,
    });
    if (confirmed) rollback.mutate(action.id);
  }

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

  const pendingItems = pendingQ.data?.items ?? [];
  const pendingTotal = pendingQ.data?.total ?? 0;
  const pendingCount = overviewQ.data?.pending_actions ?? pendingTotal;

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
            onChange={(e) => setActionFilter(e.target.value as ResponseActionType | "")}
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
            <h3 className="text-sm font-semibold text-slate-200">Pending queue</h3>
            <p className="text-xs text-slate-500">
              {pendingTotal} action(s) awaiting decision
              {pendingItems.length < pendingTotal &&
                ` · showing first ${pendingItems.length}`}
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
        ) : pendingItems.length === 0 ? (
          <EmptyState
            title="No pending actions"
            description="High-severity recommendations auto-executed; the rest were already resolved."
          />
        ) : (
          <ul className="divide-y divide-slate-800/70">
            {pendingItems.map((a) => (
              <PendingActionRow
                key={a.id}
                action={a}
                isApproving={approve.isPending && approve.variables?.id === a.id}
                isRejecting={reject.isPending && reject.variables?.id === a.id}
                onApprove={() => handleApprove(a)}
                onReject={() => handleReject(a)}
              />
            ))}
          </ul>
        )}
      </Card>

      {/* Recent activity */}
      <Card padding="none">
        <div className="border-b border-slate-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-200">Action execution history</h3>
          <p className="text-xs text-slate-500">
            Last 50 response actions. The <span className="font-medium">Mode</span> column always
            shows whether an action was simulated or lab-executed.
          </p>
        </div>

        {recentQ.isLoading ? (
          <div className="flex justify-center p-8 text-slate-400">
            <Spinner />
          </div>
        ) : recentQ.data?.length === 0 ? (
          <EmptyState title="No response activity yet" />
        ) : (
          <Table aria-label="Recent response actions">
            <Thead>
              <Tr>
                <Th>#</Th>
                <Th>Alert</Th>
                <Th>Action</Th>
                <Th>Mode</Th>
                <Th>Status</Th>
                <Th>Decided by</Th>
                <Th>Executed</Th>
                <Th>
                  <span className="sr-only">Rollback</span>
                </Th>
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
                  <Td>
                    <Badge tone={executionModeTone(a)}>{executionModeLabel(a)}</Badge>
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
                  <Td>
                    {canRollback(a) ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={rollback.isPending && rollback.variables === a.id}
                        onClick={() => handleRollback(a)}
                      >
                        {rollback.isPending && rollback.variables === a.id && (
                          <Spinner className="h-3 w-3" />
                        )}
                        Roll back
                      </Button>
                    ) : a.rollback_status === "ROLLED_BACK" ? (
                      <span className="text-xs text-slate-500">rolled back</span>
                    ) : null}
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
  onReject: () => void;
}

function PendingActionRow({
  action,
  isApproving,
  isRejecting,
  onApprove,
  onReject,
}: PendingRowProps) {
  const [open, setOpen] = useState(false);
  const realLab = isRealLabAction(action);
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
            <Badge tone={executionModeTone(action)}>{executionModeLabel(action)}</Badge>
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
          {realLab && (
            <p className="mt-2 rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-300">
              ⚠ {LAB_APPROVE_WARNING} Approving runs a real action against the configured lab
              target and will require typed confirmation + a reason.
            </p>
          )}
          <p className="mt-2 text-sm text-slate-300">{rationale}</p>
          {Object.keys(extraPayload).length > 0 && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="mt-2 rounded text-xs text-slate-400 hover:text-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
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
            variant={realLab ? "danger" : "primary"}
            size="sm"
            disabled={isApproving || isRejecting}
            onClick={onApprove}
          >
            {isApproving && <Spinner className="h-3 w-3" />}
            {realLab ? "Approve (LAB)" : "Approve"}
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={isApproving || isRejecting}
            onClick={onReject}
          >
            {isRejecting && <Spinner className="h-3 w-3" />}
            Reject
          </Button>
        </div>
      </div>
    </li>
  );
}
