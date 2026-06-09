import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { responseApi } from "@/lib/api";
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
import type { AlertDetail, ResponseActionOut } from "@/lib/types";

interface ResponseActionsTableProps {
  alertId: number;
  actions: ResponseActionOut[];
}

export function ResponseActionsTable({ alertId, actions }: ResponseActionsTableProps) {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const { user } = useAuth();
  const analystId = user?.username;

  const alertKey = ["alert", alertId] as const;

  // Optimistically patch one action in the cached AlertDetail; returns a context
  // with the snapshot so onError can roll back to server truth.
  const patchAction = async (id: number, patch: Partial<ResponseActionOut>) => {
    await qc.cancelQueries({ queryKey: alertKey });
    const prev = qc.getQueryData<AlertDetail>(alertKey);
    if (prev) {
      qc.setQueryData<AlertDetail>(alertKey, {
        ...prev,
        actions: prev.actions.map((a) => (a.id === id ? { ...a, ...patch } : a)),
      });
    }
    return { prev };
  };

  const rollbackCache = (ctx: { prev?: AlertDetail } | undefined) => {
    if (ctx?.prev) qc.setQueryData(alertKey, ctx.prev);
  };

  const settle = () => {
    qc.invalidateQueries({ queryKey: alertKey });
    qc.invalidateQueries({ queryKey: ["response"] });
  };

  const approveMut = useMutation({
    mutationFn: ({ id, note }: { id: number; note?: string }) =>
      responseApi.approveResponseAction(id, { analyst_id: analystId, note }),
    onMutate: ({ id }) => patchAction(id, { status: "EXECUTED", executed: true }),
    onError: (err, _vars, ctx) => {
      rollbackCache(ctx);
      toast.error(errorMessage(err, "Could not approve the action."));
    },
    onSuccess: () => toast.success("Response action approved."),
    onSettled: settle,
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      responseApi.rejectResponseAction(id, { analyst_id: analystId, reason }),
    onMutate: ({ id }) => patchAction(id, { status: "REJECTED" }),
    onError: (err, _vars, ctx) => {
      rollbackCache(ctx);
      toast.error(errorMessage(err, "Could not reject the action."));
    },
    onSuccess: () => toast.success("Response action rejected."),
    onSettled: settle,
  });

  const rollbackMut = useMutation({
    mutationFn: (id: number) =>
      responseApi.rollbackResponseAction(id, { analyst_id: analystId }),
    onError: (err) => toast.error(errorMessage(err, "Rollback failed.")),
    onSuccess: () => toast.success("Lab action rolled back."),
    onSettled: settle,
  });

  async function approveAction(act: ResponseActionOut) {
    if (!isRealLabAction(act)) {
      approveMut.mutate({ id: act.id });
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
          <span className="font-mono">{String(act.payload?.target_ip ?? "the lab")}</span>.{" "}
          {LAB_APPROVE_WARNING}
        </>
      ),
    });
    if (confirmed) approveMut.mutate({ id: act.id, note: reason });
  }

  async function rejectAction(act: ResponseActionOut) {
    const { confirmed, reason } = await confirm({
      title: `Reject action #${act.id}`,
      tone: "danger",
      confirmLabel: "Reject action",
      requireReason: true,
      reasonLabel: "Reason for rejection",
    });
    if (confirmed && reason) rejectMut.mutate({ id: act.id, reason });
  }

  async function rollbackAction(act: ResponseActionOut) {
    const { confirmed } = await confirm({
      title: `Roll back lab action #${act.id}`,
      tone: "danger",
      confirmLabel: "Roll back",
      message: `${LAB_APPROVE_WARNING} This reverts the real lab effect.`,
    });
    if (confirmed) rollbackMut.mutate(act.id);
  }

  return (
    <Card padding="none">
      <div className="flex items-start justify-between border-b border-slate-800 px-5 py-3">
        <div>
          <CardTitle>Response recommendations</CardTitle>
          <CardDescription>
            Simulated by default. A real effect is only possible for{" "}
            <span className="font-mono">LAB</span> actions; the DB enforces{" "}
            <span className="font-mono">simulated = TRUE</span> unless mode is LAB.
          </CardDescription>
        </div>
        <Badge tone="neutral">{actions.length} action(s)</Badge>
      </div>

      {actions.length === 0 ? (
        <EmptyState title="No response actions for this alert" />
      ) : (
        <Table aria-label="Response recommendations">
          <Thead>
            <Tr>
              <Th>#</Th>
              <Th>Action</Th>
              <Th>Mode</Th>
              <Th>Status</Th>
              <Th>Rationale</Th>
              <Th className="text-right">Decide</Th>
            </Tr>
          </Thead>
          <Tbody>
            {actions.map((act) => (
              <Tr key={act.id}>
                <Td className="font-mono text-slate-500">{act.id}</Td>
                <Td>
                  <Badge tone="default">{act.action_type}</Badge>
                </Td>
                <Td>
                  <Badge tone={executionModeTone(act)}>{executionModeLabel(act)}</Badge>
                </Td>
                <Td>
                  <Badge
                    tone={
                      act.status === "EXECUTED"
                        ? "success"
                        : act.status === "REJECTED"
                          ? "neutral"
                          : "warning"
                    }
                  >
                    {act.status}
                  </Badge>
                </Td>
                <Td className="max-w-md text-xs text-slate-400">
                  {(act.payload?.rationale as string | undefined) ?? "—"}
                </Td>
                <Td className="text-right">
                  {act.status === "PENDING" ? (
                    <div className="flex justify-end gap-2">
                      <Button
                        size="sm"
                        variant={isRealLabAction(act) ? "danger" : "primary"}
                        disabled={approveMut.isPending}
                        onClick={() => approveAction(act)}
                      >
                        {approveMut.isPending && approveMut.variables?.id === act.id && (
                          <Spinner className="h-3 w-3" />
                        )}
                        {isRealLabAction(act) ? "Approve (LAB)" : "Approve"}
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={rejectMut.isPending}
                        onClick={() => rejectAction(act)}
                      >
                        Reject
                      </Button>
                    </div>
                  ) : canRollback(act) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={rollbackMut.isPending}
                      onClick={() => rollbackAction(act)}
                    >
                      {rollbackMut.isPending && rollbackMut.variables === act.id && (
                        <Spinner className="h-3 w-3" />
                      )}
                      Roll back
                    </Button>
                  ) : (
                    <span className="text-xs text-slate-500">
                      {act.rollback_status === "ROLLED_BACK"
                        ? "rolled back"
                        : (act.approved_by ?? (act.executed ? "auto" : "—"))}
                    </span>
                  )}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}
