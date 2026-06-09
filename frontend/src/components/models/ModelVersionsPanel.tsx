import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { modelsApi } from "@/lib/api";
import { errorMessage } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/AuthContext";
import { useConfirm } from "@/lib/confirm/ConfirmProvider";
import { useToast } from "@/lib/toast/ToastContext";
import { formatRelative } from "@/lib/format";
import type { ModelVersion } from "@/lib/types";

export function ModelVersionsPanel() {
  const { hasRole } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const isAdmin = hasRole("ADMIN");

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
    onSuccess: (res) => {
      invalidate();
      toast.success(`Activated model ${res.version.version}.`);
    },
    onError: (e) => toast.error(errorMessage(e, "Activation failed.")),
  });

  const rollbackMut = useMutation({
    mutationFn: () => modelsApi.rollbackModel(),
    onSuccess: (res) => {
      invalidate();
      toast.success(`Rolled back to ${res.version.version}.`);
    },
    onError: (e) => toast.error(errorMessage(e, "Rollback failed.")),
  });

  async function handleActivate(v: ModelVersion) {
    const { confirmed } = await confirm({
      title: `Activate ${v.version}?`,
      confirmLabel: "Activate",
      message: `This model will start serving detection immediately, replacing the current active version.`,
    });
    if (confirmed) activateMut.mutate(v.id);
  }

  async function handleRollback() {
    const { confirmed } = await confirm({
      title: "Roll back to previous version?",
      tone: "danger",
      confirmLabel: "Roll back",
      message: "This re-activates the version that was active before the latest activation.",
    });
    if (confirmed) rollbackMut.mutate();
  }

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
            onClick={handleRollback}
            disabled={busy || versions.length < 2}
          >
            {rollbackMut.isPending && <Spinner className="h-3 w-3" />}
            Rollback
          </Button>
        )}
      </div>

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
                <Button size="sm" onClick={() => handleActivate(v)} disabled={busy}>
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
