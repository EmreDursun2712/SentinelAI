import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { auditApi } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import type { AuditCategory } from "@/lib/types";

const CATEGORIES: { key: AuditCategory; label: string; tone: "info" | "indigo" | "success" | "warning" }[] = [
  { key: "auth", label: "Auth", tone: "info" },
  { key: "model", label: "Model", tone: "indigo" },
  { key: "analyst", label: "Analyst", tone: "success" },
  { key: "response", label: "Response", tone: "warning" },
];

const TONE: Record<AuditCategory, "info" | "indigo" | "success" | "warning"> = {
  auth: "info",
  model: "indigo",
  analyst: "success",
  response: "warning",
};

const PAGE = 50;

export default function AuditPage() {
  const { hasRole } = useAuth();
  const { t } = useTranslation();
  const [selected, setSelected] = useState<Set<AuditCategory>>(new Set());
  const [limit, setLimit] = useState(PAGE);

  // Admin-only: the audit trail is accountability data.
  if (!hasRole("ADMIN")) {
    return <Navigate to="/" replace />;
  }

  const categories = [...selected];
  const auditQ = useQuery({
    queryKey: ["audit", categories, limit],
    queryFn: () => auditApi.listAudit({ category: categories, limit }),
    refetchInterval: 30_000,
  });

  function toggle(cat: AuditCategory) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
    setLimit(PAGE);
  }

  const items = auditQ.data?.items ?? [];

  return (
    <div className="space-y-4">
      <PageHeader title={t("pages.audit.title")} description={t("pages.audit.description")} />

      <Card padding="md">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Filter:</span>
          {CATEGORIES.map((c) => {
            const active = selected.has(c.key);
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => toggle(c.key)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs transition ring-1",
                  active
                    ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40"
                    : "bg-slate-800/40 text-slate-400 ring-slate-700 hover:text-slate-200",
                )}
              >
                {c.label}
              </button>
            );
          })}
          {selected.size > 0 && (
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              className="text-xs text-slate-500 underline hover:text-slate-300"
            >
              clear
            </button>
          )}
        </div>

        <div className="mt-4">
          {auditQ.isLoading ? (
            <div className="flex justify-center py-10 text-slate-400">
              <Spinner />
            </div>
          ) : auditQ.isError ? (
            <ErrorState description="Failed to load the audit trail." />
          ) : items.length === 0 ? (
            <EmptyState title="No audit events" description="Nothing recorded for this filter yet." />
          ) : (
            <Table>
              <Thead>
                <Tr>
                  <Th>Time</Th>
                  <Th>Category</Th>
                  <Th>Actor</Th>
                  <Th>Action</Th>
                  <Th>Target</Th>
                  <Th>Detail</Th>
                </Tr>
              </Thead>
              <Tbody>
                {items.map((e) => (
                  <Tr key={e.id}>
                    <Td className="whitespace-nowrap text-xs text-slate-400">
                      {formatDateTime(e.timestamp)}
                    </Td>
                    <Td>
                      <Badge tone={TONE[e.category]}>{e.category}</Badge>
                    </Td>
                    <Td className="font-mono text-slate-200">{e.actor ?? "—"}</Td>
                    <Td className="text-slate-300">{e.action}</Td>
                    <Td className="font-mono text-slate-400">{e.target ?? "—"}</Td>
                    <Td className="max-w-xs truncate text-slate-500" title={e.detail ?? ""}>
                      {e.detail ?? "—"}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </div>

        {auditQ.data?.has_more && (
          <div className="mt-3 flex justify-center">
            <Button variant="secondary" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
              Load more
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
