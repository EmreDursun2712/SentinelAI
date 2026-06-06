// Backwards-compatible re-export. The real WebSocket wiring lives in
// lib/stream/StreamProvider.tsx (a global provider that turns server events into
// TanStack Query invalidations) and lib/stream/invalidate.ts.

export {
  StreamProvider,
  useStreamStatus,
  useLiveInterval,
} from "@/lib/stream/StreamProvider";
export type { StreamEvent } from "@/lib/stream/types";
