import type { AlertStatus } from "@/lib/types";
import { Badge, type BadgeTone } from "./ui/Badge";

const TONE: Record<AlertStatus, BadgeTone> = {
  NEW: "info",
  TRIAGED: "indigo",
  AUTO_RESPONDED: "warning",
  AWAITING_ANALYST: "warning",
  INVESTIGATED: "success",
  REPORTED: "success",
  CLOSED: "neutral",
};

export function StatusPill({ status }: { status: AlertStatus }) {
  return <Badge tone={TONE[status]}>{status}</Badge>;
}
