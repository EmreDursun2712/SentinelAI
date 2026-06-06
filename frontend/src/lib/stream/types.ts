// Shape of a frame received over the /stream WebSocket.
export interface StreamEvent {
  type: string;
  payload: Record<string, unknown>;
  ts?: string;
}
