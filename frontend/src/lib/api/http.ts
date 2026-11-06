/**
 * Cortex Nexus — typed HTTP client for backend business APIs (spec §8).
 *
 * No component may call fetch() directly for Nexus APIs; route through the
 * per-domain clients which call this helper. The implementation delegates to
 * the platform auth client so domain calls share Bearer injection, request IDs,
 * timeout behavior, and the AuthProvider's 401 handling. Provides:
 *  - typed responses
 *  - timeout (AbortController)
 *  - normalized domain errors (NexusApiError with status code)
 *  - authentication header injection
 *  - no silent fallback on mutation methods
 */

import { apiRequest } from "@/lib/auth/client";
import { ApiClientError } from "@/lib/auth/errors";

export function setNexusAuthToken(_token: string | null) {
  // Kept as a source-compatible no-op for legacy callers. The centralized
  // auth client reads the session token from the single auth storage module.
}

export class NexusApiError extends Error {
  readonly status: number;
  readonly endpoint: string;
  readonly body?: unknown;
  constructor(status: number, endpoint: string, message: string, body?: unknown) {
    super(message);
    this.name = "NexusApiError";
    this.status = status;
    this.endpoint = endpoint;
    this.body = body;
  }
}

export function isNexusApiError(e: unknown): e is NexusApiError {
  return e instanceof NexusApiError;
}

export function isAuthError(e: unknown): boolean {
  return isNexusApiError(e) && (e.status === 401 || e.status === 403);
}

export function isNotFound(e: unknown): boolean {
  return isNexusApiError(e) && e.status === 404;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  query?: Record<string, string | number | undefined | null>;
  body?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

export async function request<T>(opts: RequestOptions): Promise<T> {
  try {
    return await apiRequest<T>(opts);
  } catch (e) {
    if (e instanceof ApiClientError) {
      throw new NexusApiError(e.status, opts.path, e.message, {
        request_id: e.requestId,
        details: e.details,
      });
    }
    throw e;
  }
}
