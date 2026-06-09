import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { modelsApi } from "@/lib/api";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { formatRelative } from "@/lib/format";

export function ModelVersionsPanel() {
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const isAdmin = hasRole("ADMIN");
  const [actionError, setActionError] = useState<string | null>(null);

  const modelsQ = useQuery({
    queryKey: ["models", "versions"],
    queryFn: modelsApi.listModels,
    refetchInterval: 30_000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["models", "versions"] });
    qc.invalidateQueries({ queryKey: ["detection", "model"] });
  };

  const activateMut = useMutation({
    mutationFn: (id: number) => modelsApi.activateModel(id),
    onSuccess: () => {
      setActionError(null);
      invalidate();
    },
    onError: (e) => setActionError(errorMessage(e, "Activation failed.")),
  });

  const rollbackMut = useMutation({
    mutationFn: () => modelsApi.rollbackModel(),
    onSuccess: () => {
      setActionError(null);
      invalidate();
    },
    onError: (e) => setActionError(errorMessage(e, "Rollback failed.")),
  });

  const versions = modelsQ.data?.items ?? [];
  const busy = activateMut.isPending || rollbackMut.isPending;

  return (
    <Card padding="md">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Model versions</h3>
          <p className="text-xs text-slate-500">
            Registered artifacts. Activate to serve; rollback restores the previous one.
          </p>
        </div>
        {isAdmin && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => rollbackMut.mutate()}
            disabled={busy || versions.length < 2}
          >
            {rollbackMut.isPending && <Spinner className="h-3 w-3" />}
            Rollback
          </Button>
        )}
      </div>

      {actionError && <p className="mt-2 text-xs text-rose-400">{actionError}</p>}

      {modelsQ.isLoading ? (
        <div className="flex justify-center py-6 text-slate-400">
          <Spinner />
        </div>
      ) : versions.length === 0 ? (
        <p className="mt-4 text-xs text-slate-500">
          No model versions registered. Train a model and stage it under{" "}
          <span className="font-mono">ml/artifacts/</span>.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {versions.map((v) => (
            <li
              key={v.id}
              className="flex items-center justify-between gap-3 rounded-md border border-slate-800 bg-slate-900/40 p-3"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate font-mono text-xs text-slate-200">{v.version}</span>
                  {v.is_active && <Badge tone="success">active</Badge>}
                </div>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  {v.algorithm} · {v.feature_order.length} features ·{" "}
                  {v.trained_at ? formatRelative(v.trained_at) : "—"}
                </p>
              </div>
              {isAdmin && !v.is_active && (
                <Button
                  size="sm"
                  onClick={() => activateMut.mutate(v.id)}
                  disabled={busy}
                >
                  Activate
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
