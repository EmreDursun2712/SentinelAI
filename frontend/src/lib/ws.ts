import { useEffect, useRef, useState } from "react";

const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? "ws://localhost:8000/api/v1";

export type StreamEvent = {
  type: string;
  payload: Record<string, unknown>;
};

export function useStream(): { connected: boolean; lastEvent: StreamEvent | null } {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<StreamEvent | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const socket = new WebSocket(`${WS_BASE}/stream`);
    socketRef.current = socket;

    socket.addEventListener("open", () => setConnected(true));
    socket.addEventListener("close", () => setConnected(false));
    socket.addEventListener("message", (ev) => {
      try {
        const parsed = JSON.parse(ev.data) as StreamEvent;
        setLastEvent(parsed);
      } catch {
        // ignore malformed messages
      }
    });

    return () => {
      socket.close();
    };
  }, []);

  return { connected, lastEvent };
}
