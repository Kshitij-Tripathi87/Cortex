/**
 * Cortex Nexus — WebSocket Real-time Client (Track X2 & X6)
 *
 * Handles:
 * - Graph delta streams
 * - Signal updates
 * - Decision invalidation notifications
 * - Agent message streaming
 * - Reconciliation events
 */

export type RealtimeEventType =
  | "graph.delta"
  | "signal.update"
  | "decision.invalidated"
  | "agent.message"
  | "reconciliation"
  | "world_state.update";

export interface RealtimeEvent<T = any> {
  event_id: string;
  event_type: RealtimeEventType;
  timestamp: string;
  world_state_version: number;
  graph_version: string;
  payload: T;
}

export interface GraphDeltaPayload {
  added_nodes: string[];
  removed_nodes: string[];
  added_edges: string[];
  removed_edges: string[];
  updated_nodes: string[];
  updated_edges: string[];
}

export interface SignalUpdatePayload {
  signal_id: string;
  action: "created" | "updated" | "resolved" | "escalated";
  signal: any;
}

export interface DecisionInvalidatedPayload {
  decision_id: string;
  reason: string;
  dependent_entities: string[];
  dependent_signals: string[];
}

export interface AgentMessagePayload {
  message_id: string;
  agent_id: string;
  content: string;
  phase: string;
  evidence_refs: string[];
}

export interface WorldStateUpdatePayload {
  version: number;
  changed_entities: string[];
  changed_signals: string[];
}

type EventHandler<T = any> = (event: RealtimeEvent<T>) => void;

class NexusRealtimeClient {
  private ws: WebSocket | null = null;
  private url: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private handlers: Map<RealtimeEventType, Set<EventHandler>> = new Map();
  private connectionState: "disconnected" | "connecting" | "connected" | "reconnecting" = "disconnected";
  private stateChangeHandlers: Set<(state: typeof this.connectionState) => void> = new Set();
  private pingInterval: NodeJS.Timeout | null = null;

  constructor() {
    const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
    this.url = base.replace(/^http/, "ws") + "/ws/realtime";
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.setConnectionState("connecting");

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.setConnectionState("connected");
        this.startPing();
      };

      this.ws.onmessage = (event) => {
        try {
          const data: RealtimeEvent = JSON.parse(event.data);
          this.dispatchEvent(data);
        } catch (e) {
          console.error("Failed to parse realtime event:", e);
        }
      };

      this.ws.onclose = () => {
        this.stopPing();
        this.setConnectionState("disconnected");
        this.scheduleReconnect();
      };

      this.ws.onerror = (error) => {
        console.error("WebSocket error:", error);
      };
    } catch (e) {
      console.error("Failed to create WebSocket:", e);
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.stopPing();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setConnectionState("disconnected");
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn("Max reconnect attempts reached");
      return;
    }

    this.setConnectionState("reconnecting");
    const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts);
    this.reconnectAttempts++;

    setTimeout(() => {
      this.connect();
    }, delay);
  }

  private startPing(): void {
    this.pingInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);
  }

  private stopPing(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private setConnectionState(state: typeof this.connectionState): void {
    this.connectionState = state;
    this.stateChangeHandlers.forEach((handler) => handler(state));
  }

  onStateChange(handler: (state: typeof this.connectionState) => void): () => void {
    this.stateChangeHandlers.add(handler);
    return () => this.stateChangeHandlers.delete(handler);
  }

  on<T = any>(eventType: RealtimeEventType, handler: EventHandler<T>): () => void {
    if (!this.handlers.has(eventType)) {
      this.handlers.set(eventType, new Set());
    }
    this.handlers.get(eventType)!.add(handler);
    return () => this.off(eventType, handler);
  }

  off<T = any>(eventType: RealtimeEventType, handler: EventHandler<T>): void {
    this.handlers.get(eventType)?.delete(handler);
  }

  private dispatchEvent<T = any>(event: RealtimeEvent<T>): void {
    const handlers = this.handlers.get(event.event_type);
    if (handlers) {
      handlers.forEach((handler) => {
        try {
          handler(event);
        } catch (e) {
          console.error(`Error in handler for ${event.event_type}:`, e);
        }
      });
    }
  }

  getConnectionState(): typeof this.connectionState {
    return this.connectionState;
  }
}

// Singleton instance
export const nexusRealtime = new NexusRealtimeClient();

// Convenience hooks
export function useRealtimeEvent<T = any>(
  eventType: RealtimeEventType,
  handler: EventHandler<T>,
  deps: any[] = []
) {
  const { useEffect } = require("react");
  useEffect(() => {
    const unsubscribe = nexusRealtime.on(eventType, handler);
    return unsubscribe;
  }, deps);
}

export function useRealtimeConnection() {
  const { useState, useEffect } = require("react");
  const [state, setState] = useState(nexusRealtime.getConnectionState());

  useEffect(() => {
    const unsubscribe = nexusRealtime.onStateChange(setState);
    nexusRealtime.connect();
    return () => {
      unsubscribe();
      nexusRealtime.disconnect();
    };
  }, []);

  return state;
}