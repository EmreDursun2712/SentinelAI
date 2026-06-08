import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, type BadgeTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { tasksApi } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";
import { useLiveInterval } from "@/lib/stream/StreamProvider";
import type { Task, TaskStatus } from "@/lib/types";

const STATUS_TONE: Record<TaskStatus, BadgeTone> = {
  PENDING: "neutral",
  RUNNING: "info",
  SUCCEEDED: "success",
  FAILED: "danger",
  CANCELLED: "warning",
};

function summarize(task: Task): string {
  if (task.error) return task.error;
  if (task.result && Object.keys(task.result).length > 0) {
    return Object.entries(task.result)
      .slice(0, 3)
      .map(([k, v]) => `${k}=${String(v)}`)
      .join(" · ");
  }
  return "—";
}

export function TasksPanel() {
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const tasksQ = useQuery({
    queryKey: ["tasks"],
    queryFn: () => tasksApi.listTasks({ limit: 10 }),
    // WS task.updated events invalidate ["tasks"]; poll as a fallback.
    refetchInterval: useLiveInterval(5_000),
  });

  const enqueue = useMutation({
    mutationFn: (kind: "detection" | "drift" | "daily") =>
      kind === "detection"
        ? tasksApi.runDetection()
        : kind === "drift"
          ? tasksApi.runDrift()
          : tasksApi.runDailySummary(),
    onSuccess: () => {
      setActionError(null);
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: () => setActionError("Could not enqueue the task (rate-limited or not permitted)."),
  });

  const canRun = hasRole("ANALYST");
  const tasks = tasksQ.data?.items ?? [];

  return (
    <Card padding="md">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Background tasks</h3>
          <p className="text-xs text-slate-500">Long jobs run on the worker; status updates live.</p>
        </div>
        {canRun && (
          <div className="flex gap-2">
            <Button size="sm" onClick={() => enqueue.mutate("detection")} disabled={enqueue.isPending}>
              Run detection
            </Button>
            <Button size="sm" onClick={() => enqueue.mutate("drift")} disabled={enqueue.isPending}>
              Run drift
            </Button>
            <Button size="sm" onClick={() => enqueue.mutate("daily")} disabled={enqueue.isPending}>
              Daily summary
            </Button>
          </div>
        )}
      </div>

      {actionError && <p className="mt-2 text-xs text-rose-400">{actionError}</p>}

      <ul className="mt-4 space-y-2">
        {tasks.length === 0 && (
          <li className="text-xs text-slate-500">No background tasks yet.</li>
        )}
        {tasks.map((task) => (
          <li key={task.id} className="rounded-md border border-slate-800 bg-slate-900/40 p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-xs text-slate-300">{task.kind}</span>
              <Badge tone={STATUS_TONE[task.status]}>{task.status}</Badge>
            </div>
            {task.status === "RUNNING" && (
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full bg-emerald-500 transition-all"
                  style={{ width: `${Math.max(2, task.progress)}%` }}
                />
              </div>
            )}
            <p className="mt-1.5 truncate text-[11px] text-slate-500">{summarize(task)}</p>
          </li>
        ))}
      </ul>
    </Card>
  );
}
