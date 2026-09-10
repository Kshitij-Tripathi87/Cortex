/**
 * @deprecated B4: superseded by the centralized client in
 * `@/lib/realtime/client` (sequence gate, cursor resume, replay/resync).
 * Kept for reference; new code must use `RealtimeClient`.
 */
/**
 * Nexus Real-Time Streaming Client — WebSocket connection for live Cockpit updates.
 *
 * Streams:
 * - World state mutations
 * - Deliberation & Decision Room message feeds
 * - Simulation progress updates
 * - Human decision approvals
 */

type MessageListener = (data: any) => void;

export class NexusRealtimeClient {
  private ws: WebSocket | null = null;
  private url: string;
  private listeners: Map<string, Set<MessageListener>> = new Map();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private isClosedExplicitly = false;

  constructor(
    private workspaceId: string = "default_workspace",
    private tenantId: string = "default_tenant",
    baseUrl?: string,
  ) {
    const defaultHost = typeof window !== "undefined" ? window.location.hostname : "localhost";
    const base = baseUrl || (process.env.NEXT_PUBLIC_API_URL?.replace("http", "ws") || `ws://${defaultHost}:8000`);
    this.url = `${base}/api/v1/realtime/ws?workspace_id=${encodeURIComponent(workspaceId)}&tenant_id=${encodeURIComponent(tenantId)}`;
  }

  public connect(): void {
    if (typeof window === "undefined") return;
    this.isClosedExplicitly = false;

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.emit("connection_status", { status: "connected" });
      };

      this.ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          const channel = payload.channel || payload.type || "*";
          this.emit(channel, payload);
          this.emit("*", payload);
        } catch {
          // ignore malformed frame
        }
      };

      this.ws.onclose = () => {
        if (!this.isClosedExplicitly) {
          this.scheduleReconnect();
        }
        this.emit("connection_status", { status: "disconnected" });
      };

      this.ws.onerror = (err) => {
        this.emit("error", err);
      };
    } catch {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts += 1;
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000);
      setTimeout(() => this.connect(), delay);
    }
  }

  public subscribe(channel: string, listener: MessageListener): () => void {
    if (!this.listeners.has(channel)) {
      this.listeners.set(channel, new Set());
    }
    this.listeners.get(channel)!.add(listener);

    // Return unbind function
    return () => {
      this.listeners.get(channel)?.delete(listener);
    };
  }

  private emit(channel: string, data: any): void {
    const channelListeners = this.listeners.get(channel);
    if (channelListeners) {
      channelListeners.forEach((listener) => {
        try {
          listener(data);
        } catch {
          // preserve listener isolation
        }
      });
    }
  }

  public close(): void {
    this.isClosedExplicitly = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
