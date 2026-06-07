import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardDescription, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { responseApi } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";
import {
  LAB_APPROVE_WARNING,
  canRollback,
  executionModeLabel,
  executionModeTone,
  isRealLabAction,
} from "@/lib/response";
import type { ResponseActionOut } from "@/lib/types";

interface ResponseActionsTableProps {
  alertId: number;
  actions: ResponseActionOut[];
}

export function ResponseActionsTable({
  alertId,
  actions,
}: ResponseActionsTableProps) {
  const qc = useQueryClient();
  const { user } = useAuth();
  const analystId = user?.username;

  const approveMut = useMutation({
    mutationFn: (id: number) =>
      responseApi.approveResponseAction(id, { analyst_id: analystId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert", alertId] });
      qc.invalidateQueries({ queryKey: ["response"] });
    },
  });
  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: number; reason: string }) =>
      responseApi.rejectResponseAction(id, {
        analyst_id: analystId,
        reason,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert", alertId] });
      qc.invalidateQueries({ queryKey: ["response"] });
    },
  });
  const rollbackMut = useMutation({
    mutationFn: (id: number) =>
      responseApi.rollbackResponseAction(id, { analyst_id: analystId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert", alertId] });
      qc.invalidateQueries({ queryKey: ["response"] });
    },
  });

  function approveAction(act: ResponseActionOut) {
    if (!isRealLabAction(act)) {
      approveMut.mutate(act.id);
      return;
    }
    const reason = window.prompt(
      `⚠ Real LAB action on ${String(act.payload?.target_ip ?? "the lab")}.\n` +
        `${LAB_APPROVE_WARNING}\nType a reason to confirm:`,
      "",
    );
    if (reason && reason.trim()) approveMut.mutate(act.id);
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
        <Table>
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
                        {approveMut.isPending && approveMut.variables === act.id && (
                          <Spinner className="h-3 w-3" />
                        )}
                        {isRealLabAction(act) ? "Approve (LAB)" : "Approve"}
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={rejectMut.isPending}
                        onClick={() => {
                          const reason = window.prompt(
                            "Reason for rejection?",
                            "",
                          );
                          if (reason && reason.trim())
                            rejectMut.mutate({ id: act.id, reason });
                        }}
                      >
                        Reject
                      </Button>
                    </div>
                  ) : canRollback(act) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={rollbackMut.isPending}
                      onClick={() => {
                        if (window.confirm(`Roll back lab action #${act.id}?`))
                          rollbackMut.mutate(act.id);
                      }}
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
