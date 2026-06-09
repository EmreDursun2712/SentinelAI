import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  ArrowRightIcon,
  CheckIcon,
  IngestionIcon,
  PlayIcon,
  RefreshIcon,
} from "@/components/icons";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Spinner } from "@/components/ui/Spinner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/Table";
import { detectionApi, ingestionApi } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast/ToastContext";
import { cn } from "@/lib/cn";
import { formatDateTime, formatRelative } from "@/lib/format";
import type {
  DetectionRunSummary,
  IngestionJob,
  IngestionStatus,
  IngestionSummary,
} from "@/lib/types";

const STATUS_TONE: Record<IngestionStatus, "info" | "warning" | "success" | "danger"> = {
  PENDING: "info",
  RUNNING: "warning",
  COMPLETED: "success",
  FAILED: "danger",
};

type StepState = "pending" | "current" | "in_progress" | "done" | "error";

export default function IngestionPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const step2Ref = useRef<HTMLDivElement>(null);
  const step3Ref = useRef<HTMLDivElement>(null);

  const [chosenFile, setChosenFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);

  // Workflow state — pure UI; the backend doesn't know about "the current demo run".
  const [lastSummary, setLastSummary] = useState<IngestionSummary | null>(null);
  const [lastDetection, setLastDetection] = useState<DetectionRunSummary | null>(null);
  const [step1Error, setStep1Error] = useState<string | null>(null);
  const [step2Error, setStep2Error] = useState<string | null>(null);

  const step1Done =
    lastSummary?.status === "COMPLETED" && (lastSummary?.valid_rows ?? 0) > 0;
  const step2Done = lastDetection != null;

  // Scroll the next step into focus once the previous one finishes.
  useEffect(() => {
    if (step1Done && step2Ref.current) {
      step2Ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [step1Done]);
  useEffect(() => {
    if (step2Done && step3Ref.current) {
      step3Ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [step2Done]);

  // -------- mutations --------

  const uploadMut = useMutation({
    mutationFn: (file: File) => ingestionApi.uploadCsv(file),
    onSuccess: (summary) => {
      setLastSummary(summary);
      setLastDetection(null);
      setStep1Error(null);
      setStep2Error(null);
      setChosenFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["ingest", "jobs"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(`Ingested ${summary.valid_rows} valid row(s) from ${summary.source}.`);
    },
    onError: (err) => {
      setStep1Error(formatError(err));
      toast.error(formatError(err), { title: "Upload failed" });
    },
  });

  const replayMut = useMutation({
    mutationFn: () => ingestionApi.replayCsv("samples/sample_flows.csv", 50),
    onSuccess: (summary) => {
      setLastSummary(summary);
      setLastDetection(null);
      setStep1Error(null);
      setStep2Error(null);
      qc.invalidateQueries({ queryKey: ["ingest", "jobs"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(`Replayed sample — ${summary.valid_rows} row(s) ingested.`);
    },
    onError: (err) => {
      setStep1Error(formatError(err));
      toast.error(formatError(err), { title: "Replay failed" });
    },
  });

  const detectionMut = useMutation({
    mutationFn: () => detectionApi.runDetection({ limit: 5000 }),
    onSuccess: (summary) => {
      setLastDetection(summary);
      setStep2Error(null);
      qc.invalidateQueries({ queryKey: ["alerts"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["response"] });
      toast.success(
        `Detection done — ${summary.alerts_created} alert(s) from ${summary.processed} event(s).`,
      );
    },
    onError: (err) => {
      setStep2Error(formatError(err));
      toast.error(formatError(err), { title: "Detection failed" });
    },
  });

  // -------- helpers --------

  const resetWorkflow = () => {
    setLastSummary(null);
    setLastDetection(null);
    setStep1Error(null);
    setStep2Error(null);
    setChosenFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  // -------- jobs feed --------

  const jobsQ = useQuery({
    queryKey: ["ingest", "jobs"],
    queryFn: () => ingestionApi.listIngestionJobs(20),
    refetchInterval: 5_000,
  });

  const sensorQ = useQuery({
    queryKey: ["ingest", "sensor", "status"],
    queryFn: ingestionApi.getSensorStatus,
    refetchInterval: 10_000,
  });

  // -------- step states --------

  const step1State: StepState = step1Error
    ? "error"
    : uploadMut.isPending || replayMut.isPending
      ? "in_progress"
      : step1Done
        ? "done"
        : "current";

  const step2State: StepState = !step1Done
    ? "pending"
    : step2Error
      ? "error"
      : detectionMut.isPending
        ? "in_progress"
        : step2Done
          ? "done"
          : "current";

  const step3State: StepState = !step2Done ? "pending" : "current";

  return (
    <section className="space-y-6">
      <PageHeader
        title="Ingestion → Detection → Alerts"
        description="Upload a CSV of network flows, run detection, and walk straight into the resulting alerts."
        actions={
          (lastSummary || lastDetection) && (
            <Button variant="ghost" onClick={resetWorkflow}>
              <RefreshIcon className="h-3.5 w-3.5" />
              Reset workflow
            </Button>
          )
        }
      />

      {/* Live sensor (lab-only). Liveness is inferred from recent ingest
          activity — the backend doesn't run the sensor process itself. */}
      <Card padding="none">
        <div className="flex items-center justify-between px-5 py-3">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "inline-block h-2 w-2 rounded-full",
                sensorQ.data?.live ? "bg-emerald-400" : "bg-slate-600",
              )}
            />
            <div>
              <h3 className="text-sm font-semibold text-slate-200">Live sensor</h3>
              <p className="text-xs text-slate-500">
                Zeek/Suricata flow feed · lab-only, off by default
              </p>
            </div>
          </div>
          <div className="text-right text-xs">
            <Badge tone={sensorQ.data?.live ? "success" : "neutral"}>
              {sensorQ.isError ? "unknown" : sensorQ.data?.live ? "receiving" : "idle"}
            </Badge>
            {sensorQ.data?.last_event_at && (
              <p className="mt-1 text-slate-500">
                last flow {formatRelative(sensorQ.data.last_event_at)} ·{" "}
                {sensorQ.data.events_recent} in last{" "}
                {sensorQ.data.live_window_seconds}s
              </p>
            )}
          </div>
        </div>
      </Card>

      {/* ---------- Step 1: Upload ---------- */}
      <StepCard
        step={1}
        title="Upload a CSV of network flows"
        description="Drop a CIC-IDS2017-style file or replay the bundled sample. Each ingest is recorded as a job."
        state={step1State}
      >
        <div className="space-y-4">
          {/* Drop zone */}
          <div
            onDragEnter={() => setDragging(true)}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files?.[0];
              if (f) {
                if (!f.name.toLowerCase().endsWith(".csv")) {
                  setStep1Error("Only .csv files are accepted.");
                  return;
                }
                setChosenFile(f);
                setStep1Error(null);
              }
            }}
            className={cn(
              "rounded-md border-2 border-dashed p-6 text-center transition",
              dragging
                ? "border-emerald-500 bg-emerald-500/5"
                : "border-slate-700 bg-slate-900/40 hover:border-slate-600",
            )}
          >
            <IngestionIcon className="mx-auto mb-3 h-7 w-7 text-slate-500" />
            <p className="text-sm text-slate-300">
              Drag a <span className="font-mono">.csv</span> file here, or{" "}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="text-emerald-400 underline-offset-2 hover:underline"
              >
                click to browse
              </button>
              .
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Tolerates CIC-IDS2017 column-name variants. Schema is documented in{" "}
              <span className="font-mono">docs/INGESTION.md</span>.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setChosenFile(f);
                setStep1Error(null);
              }}
            />
            {chosenFile && (
              <p className="mt-3 inline-flex items-center gap-2 rounded bg-slate-800/70 px-2 py-1 text-xs text-slate-300">
                <span className="font-mono">{chosenFile.name}</span>
                <span className="text-slate-500">
                  ({(chosenFile.size / 1024).toFixed(1)} KB)
                </span>
              </p>
            )}
          </div>

          {/* Actions row */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              disabled={!chosenFile || uploadMut.isPending}
              onClick={() => chosenFile && uploadMut.mutate(chosenFile)}
            >
              {uploadMut.isPending && <Spinner className="h-3 w-3" />}
              Upload + ingest
            </Button>
            <Button
              variant="secondary"
              disabled={replayMut.isPending}
              onClick={() => replayMut.mutate()}
            >
              {replayMut.isPending && <Spinner className="h-3 w-3" />}
              <PlayIcon className="h-3.5 w-3.5" />
              Replay bundled sample
            </Button>
            {step1Error && (
              <span className="text-xs text-rose-400">{step1Error}</span>
            )}
          </div>

          {/* Result */}
          {lastSummary && (
            <IngestionSummaryBlock summary={lastSummary} />
          )}
        </div>
      </StepCard>

      {/* ---------- Step 2: Detection ---------- */}
      <div ref={step2Ref}>
        <StepCard
          step={2}
          title="Run detection on the ingested events"
          description="The detection agent processes every un-detected event. Triage + response fire inline."
          state={step2State}
        >
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="primary"
                disabled={!step1Done || detectionMut.isPending}
                onClick={() => detectionMut.mutate()}
              >
                {detectionMut.isPending && <Spinner className="h-3 w-3" />}
                Run detection now
              </Button>
              {!step1Done ? (
                <span className="text-xs text-slate-500">
                  Complete step 1 first.
                </span>
              ) : (
                <span className="text-xs text-slate-500">
                  Processes up to 5,000 undetected events per click.
                </span>
              )}
              {step2Error && (
                <span className="text-xs text-rose-400">{step2Error}</span>
              )}
            </div>

            {lastDetection && (
              <DetectionSummaryBlock summary={lastDetection} />
            )}
          </div>
        </StepCard>
      </div>

      {/* ---------- Step 3: Review ---------- */}
      <div ref={step3Ref}>
        <StepCard
          step={3}
          title="Review the generated alerts"
          description="Jump into the Alerts console — newest first — and dispose of them."
          state={step3State}
        >
          <div className="space-y-4">
            {!step2Done ? (
              <p className="text-sm text-slate-500">
                Detection hasn't run yet. Complete step 2 to enable this step.
              </p>
            ) : lastDetection && lastDetection.alerts_created === 0 ? (
              <div className="rounded-md border border-slate-800 bg-slate-900/40 p-4 text-sm text-slate-400">
                Detection processed {lastDetection.processed} event(s) but the
                model didn't flag any as suspicious. Try ingesting a noisier
                CSV — the bundled sample contains DDoS, BruteForce, and PortScan
                rows that should reliably trip the detector.
              </div>
            ) : (
              <>
                <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-4">
                  <p className="text-sm text-emerald-200">
                    <strong>
                      {lastDetection?.alerts_created ?? 0} alert(s)
                    </strong>{" "}
                    were created from this ingestion run. They're already
                    triaged and have response recommendations.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="primary"
                    onClick={() => navigate("/alerts?sort=created_at")}
                  >
                    Open Alerts console
                    <ArrowRightIcon className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => navigate("/response")}
                  >
                    Go to Response Center
                  </Button>
                  <Link
                    to="/"
                    className="text-xs text-slate-400 hover:text-slate-200"
                  >
                    or view the Dashboard →
                  </Link>
                </div>
              </>
            )}
          </div>
        </StepCard>
      </div>

      {/* ---------- Recent jobs ---------- */}
      <Card padding="none">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-200">
              Recent ingestion jobs
            </h3>
            <p className="text-xs text-slate-500">
              Auto-refreshes every 5 s · most recent first.
            </p>
          </div>
          {jobsQ.isFetching && (
            <span className="inline-flex items-center gap-1 text-xs text-slate-500">
              <Spinner className="h-3 w-3" /> refreshing
            </span>
          )}
        </div>

        {jobsQ.isLoading ? (
          <div className="flex justify-center p-8 text-slate-400">
            <Spinner />
          </div>
        ) : jobsQ.isError ? (
          <ErrorState description="Failed to load ingestion jobs." />
        ) : jobsQ.data?.length === 0 ? (
          <EmptyState title="No ingestion jobs yet" />
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>#</Th>
                <Th>Kind</Th>
                <Th>Source</Th>
                <Th>Status</Th>
                <Th className="text-right">Done</Th>
                <Th className="text-right">Failed</Th>
                <Th>Started</Th>
                <Th>Age</Th>
              </Tr>
            </Thead>
            <Tbody>
              {jobsQ.data?.map((j: IngestionJob) => (
                <Tr key={j.id}>
                  <Td className="font-mono text-slate-500">{j.id}</Td>
                  <Td>
                    <Badge tone="default">{j.kind}</Badge>
                  </Td>
                  <Td className="max-w-xs truncate font-mono text-xs text-slate-400">
                    {j.source}
                  </Td>
                  <Td>
                    <Badge tone={STATUS_TONE[j.status]}>{j.status}</Badge>
                  </Td>
                  <Td className="text-right font-mono text-slate-300">
                    {j.records_done}
                  </Td>
                  <Td className="text-right font-mono text-slate-400">
                    {j.records_failed}
                  </Td>
                  <Td className="text-xs text-slate-500">
                    {formatDateTime(j.started_at)}
                  </Td>
                  <Td className="text-xs text-slate-500">
                    {formatRelative(j.created_at)}
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

// ---------- Step card ----------

interface StepCardProps {
  step: number;
  title: string;
  description?: string;
  state: StepState;
  children: React.ReactNode;
}

function StepCard({ step, title, description, state, children }: StepCardProps) {
  const disabled = state === "pending";
  return (
    <Card
      padding="lg"
      className={cn(
        "transition",
        state === "current" && "ring-1 ring-emerald-500/40",
        state === "in_progress" && "ring-1 ring-amber-500/40",
        state === "done" && "ring-1 ring-emerald-500/30",
        state === "error" && "ring-1 ring-rose-500/40",
        disabled && "opacity-70",
      )}
    >
      <div className="mb-4 flex items-start gap-4">
        <StepBadge n={step} state={state} />
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-slate-100">{title}</h3>
          {description && (
            <p className="mt-1 text-xs text-slate-400">{description}</p>
          )}
        </div>
        <StepStatusLabel state={state} />
      </div>
      <div className={cn(disabled && "pointer-events-none")}>{children}</div>
    </Card>
  );
}

function StepBadge({ n, state }: { n: number; state: StepState }) {
  return (
    <span
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold ring-1",
        state === "pending" && "bg-slate-800 text-slate-500 ring-slate-700",
        state === "current" &&
          "bg-emerald-500/15 text-emerald-300 ring-emerald-500/50",
        state === "in_progress" &&
          "bg-amber-500/15 text-amber-300 ring-amber-500/50",
        state === "done" && "bg-emerald-500 text-slate-950 ring-emerald-400",
        state === "error" && "bg-rose-500 text-slate-950 ring-rose-400",
      )}
    >
      {state === "done" ? (
        <CheckIcon className="h-4 w-4" />
      ) : state === "in_progress" ? (
        <Spinner className="h-4 w-4" />
      ) : (
        n
      )}
    </span>
  );
}

function StepStatusLabel({ state }: { state: StepState }) {
  if (state === "done") return <Badge tone="success">done</Badge>;
  if (state === "in_progress") return <Badge tone="warning">running</Badge>;
  if (state === "current") return <Badge tone="info">ready</Badge>;
  if (state === "error") return <Badge tone="danger">failed</Badge>;
  return <Badge tone="neutral">pending</Badge>;
}

// ---------- Result panels ----------

function IngestionSummaryBlock({ summary }: { summary: IngestionSummary }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={STATUS_TONE[summary.status]}>{summary.status}</Badge>
        <span className="text-xs text-slate-400">
          job <span className="font-mono">#{summary.job_id}</span>
        </span>
        <span className="text-xs text-slate-500">
          source: <span className="font-mono">{summary.source}</span>
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <Metric label="Total rows" value={summary.total_rows} />
        <Metric label="Valid" value={summary.valid_rows} tone="success" />
        <Metric
          label="Invalid"
          value={summary.invalid_rows}
          tone={summary.invalid_rows > 0 ? "danger" : "default"}
        />
      </dl>
      {summary.errors_truncated && (
        <p className="mt-2 text-xs text-amber-400">
          Errors list truncated — only the first 50 are shown.
        </p>
      )}
      {summary.errors.length > 0 && (
        <details className="mt-3 text-xs text-slate-400">
          <summary className="cursor-pointer text-slate-300">
            {summary.errors.length} row error(s)
          </summary>
          <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto font-mono">
            {summary.errors.map((err) => (
              <li key={err.row_number}>
                <span className="text-rose-400">row {err.row_number}:</span>{" "}
                {err.message}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function DetectionSummaryBlock({ summary }: { summary: DetectionRunSummary }) {
  const labels = Object.entries(summary.by_label).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-4">
      <p className="text-xs text-slate-400">
        Model:{" "}
        <span className="font-mono text-slate-300">
          {summary.model_name}@{summary.model_version}
        </span>
      </p>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <Metric label="Processed" value={summary.processed} />
        <Metric
          label="Alerts created"
          value={summary.alerts_created}
          tone={summary.alerts_created > 0 ? "warning" : "default"}
        />
        <Metric label="Benign" value={summary.benign_count} tone="success" />
      </dl>
      {labels.length > 0 && (
        <div className="mt-3">
          <p className="text-[10px] uppercase tracking-widest text-slate-500">
            By predicted label
          </p>
          <div className="mt-1 flex flex-wrap gap-2">
            {labels.map(([name, count]) => (
              <Badge key={name} tone={name === "BENIGN" ? "neutral" : "info"}>
                {name}: {count}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "success" | "warning" | "danger";
}) {
  const toneClass = {
    default: "text-slate-200",
    success: "text-emerald-300",
    warning: "text-amber-300",
    danger: "text-rose-300",
  }[tone];
  return (
    <div className="rounded border border-slate-800 bg-slate-900/40 p-2">
      <p className="text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </p>
      <p className={cn("mt-0.5 text-lg font-semibold", toneClass)}>{value}</p>
    </div>
  );
}

// ---------- error formatter ----------

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail =
      typeof err.body === "object" && err.body !== null
        ? ((err.body as Record<string, unknown>).error as
            | { message?: string }
            | undefined
          )?.message ?? JSON.stringify(err.body)
        : String(err.body);
    return `(${err.status}) ${detail}`;
  }
  return err instanceof Error ? err.message : String(err);
}
