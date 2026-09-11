"use client";

/**
 * React bindings for the B4 RealtimeClient.
 *
 * - `useRealtimeClient` owns one client per workspace+transport: connects on
 *   mount, disconnects on unmount (StrictMode double-effects are safe —
 *   disconnect/connect is idempotent).
 * - `useRealtimeStatus` re-renders on Live/Reconnecting/Syncing transitions
 *   and exposes the terminal auth verdict (401 vs 403).
 * - `useRealtimeEvent` subscribes a handler to one domain type.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  RealtimeAuthError,
  RealtimeClient,
  RealtimeClientOptions,
  RealtimeStatus,
  type CanonicalEvent,
  type EventHandler,
} from "./client";

export function useRealtimeClient(options: RealtimeClientOptions): RealtimeClient {
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const client = useMemo(
    () =>
      new RealtimeClient({
        ...options,
        // Callbacks stay live across renders via the ref; the client
        // instance (and its cursor) is stable per workspace+transport.
        getToken: () => optionsRef.current.getToken?.() ?? null,
        authHeaders: () => {
          const headers = optionsRef.current.authHeaders;
          return typeof headers === "function" ? headers() : (headers ?? {});
        },
        onResyncRequired: (request) => optionsRef.current.onResyncRequired?.(request),
        onError: (error) => optionsRef.current.onError?.(error),
      }),
    // One client per workspace+transport identity; callbacks stay live via ref.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options.workspaceId, options.transport, options.baseUrl],
  );
  useEffect(() => {
    client.connect();
    return () => {
      client.disconnect();
    };
  }, [client]);
  return client;
}

export function useRealtimeStatus(client: RealtimeClient | null): {
  status: RealtimeStatus;
  authError: RealtimeAuthError;
  lastSeq: number;
} {
  const [status, setStatus] = useState<RealtimeStatus>(client?.getStatus() ?? "offline");
  const [authError, setAuthError] = useState<RealtimeAuthError>(
    client?.getAuthError() ?? null,
  );
  const [lastSeq, setLastSeq] = useState<number>(client?.getLastSeq() ?? 0);

  useEffect(() => {
    if (!client) {
      setStatus("offline");
      setAuthError(null);
      return;
    }
    const updateSeq = () => setLastSeq(client.getLastSeq());
    const offStatus = client.onStatus((next, changed) => {
      setStatus(next);
      setAuthError(changed.getAuthError());
      updateSeq();
    });
    const offAny = client.onAny(updateSeq);
    return () => {
      offStatus();
      offAny();
    };
  }, [client]);

  return { status, authError, lastSeq };
}

export function useRealtimeEvent(
  client: RealtimeClient | null,
  type: string,
  handler: EventHandler,
): void {
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  useEffect(() => {
    if (!client) return;
    return client.on(type, (event: CanonicalEvent) => handlerRef.current(event));
  }, [client, type]);
}
