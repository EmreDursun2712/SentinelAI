import type { AlertDisposition } from "@/lib/types";
import { Badge, type BadgeTone } from "./ui/Badge";

const TONE: Record<AlertDisposition, BadgeTone> = {
  OPEN: "info",
  UNDER_REVIEW: "warning",
  CONFIRMED: "danger",
  FALSE_POSITIVE: "neutral",
  RESOLVED: "success",
};

export function DispositionPill({ disposition }: { disposition: AlertDisposition }) {
  return <Badge tone={TONE[disposition]}>{disposition}</Badge>;
}
