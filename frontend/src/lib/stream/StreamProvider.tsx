import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useAuth } from "@/lib/auth/AuthContext";
import { getToken } from "@/lib/auth/token";
import { applyStreamInvalidation } from "@/lib/stream/invalidate";

const WS_BASE: string =
  import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000/api/v1";

const MAX_BACKOFF_MS = 30_000;

interface StreamContextValue {
  connected: boolean;
}

const StreamContext = createContext<StreamContextValue>({ connected: false });

/** Opens an authenticated WebSocket to /stream and turns server events into
 *  TanStack Query invalidations, so the UI updates without waiting for polling.
 *  Reconnects with exponential backoff; only runs while authenticated. */
export function StreamProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const retriesRef = useRef(0);

  useEffect(() => {
    if (!isAuthenticated) {
      setConnected(false);
      return;
    }

    let closedByUs = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const scheduleReconnect = () => {
      const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** retriesRef.current);
      retriesRef.current += 1;
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      const token = getToken();
      if (!token) return; // can't authenticate the socket without a token
      const ws = new WebSocket(
        `${WS_BASE}/stream?token=${encodeURIComponent(token)}`,
      );
      socket = ws;

      ws.addEventListener("open", () => {
        retriesRef.current = 0;
        setConnected(true);
      });

      ws.addEventListener("message", (ev) => {
        try {
          const msg = JSON.parse(ev.data) as { type?: string };
          if (msg?.type) applyStreamInvalidation(queryClient, msg.type);
        } catch {
          // ignore malformed frames
        }
      });

      ws.addEventListener("close", () => {
        setConnected(false);
        if (!closedByUs) scheduleReconnect();
      });

      // On error, force a close so the close handler schedules the retry.
      ws.addEventListener("error", () => ws.close());
    };

    connect();

    return () => {
      closedByUs = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
      setConnected(false);
    };
  }, [isAuthenticated, queryClient]);

  return (
    <StreamContext.Provider value={{ connected }}>
      {children}
    </StreamContext.Provider>
  );
}

export function useStreamStatus(): StreamContextValue {
  return useContext(StreamContext);
}

/** Polling interval helper: stretch the interval when the live stream is
 *  connected (events drive freshness), keep it tight as a fallback otherwise. */
export function useLiveInterval(baseMs: number): number {
  const { connected } = useStreamStatus();
  return connected ? baseMs * 5 : baseMs;
}
