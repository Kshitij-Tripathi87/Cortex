/**
 * Centralized authenticated HTTP client (B2 §7). All auth flows — and all
 * new product code — go through here. No component calls fetch() directly.
 *
 * Provides: single base-URL resolution, Bearer injection, timeout,
 * X-Request-ID correlation, normalized ApiClientError, and a single 401
 * invalidation hook owned by AuthProvider.
 */

import { ApiClientError, firstValidationMessage } from "./errors";
import { getToken } from "./token";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ClientOptions {
  method?: HttpMethod;
  /** Path under /api/v1, e.g. "/auth/me". Absolute http(s) URLs pass through. */
  path: string;
  query?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
  timeoutMs?: number;
  /** Skip Bearer injection (public endpoints). */
  anonymous?: boolean;
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 15000;

/**
 * Single configuration knob: NEXT_PUBLIC_API_URL is the backend origin
 * (e.g. http://localhost:8000). NEXT_PUBLIC_API_BASE_URL (origin + /api/v1)
 * remains honored as a legacy override so existing environments keep working.
 */
export function resolveApiBase(): string {
  const legacy = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (legacy && legacy.length > 0) return legacy.replace(/\/$/, "");
  const origin = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  return `${origin.replace(/\/$/, "")}/api/v1`;
}

function buildUrl(path: string, query?: ClientOptions["query"]): string {
  const base = path.startsWith("http") ? path : `${resolveApiBase()}${path}`;
  if (!query) return base;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

type UnauthorizedHandler = (path: string) => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** AuthProvider registers the single session-invalidation callback. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/**
 * 401s from credential-establishing endpoints are form errors (invalid
 * credentials), NOT session death — the client must not invalidate on them.
 */
const NO_INVALIDATION_PREFIXES = ["/auth/login", "/auth/signup", "/auth/reset/"];

function shouldInvalidate(path: string, status: number): boolean {
  if (status !== 401) return false;
  return !NO_INVALIDATION_PREFIXES.some((prefix) => path.startsWith(prefix));
}

function newRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `fe-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

export async function apiRequest<T>(opts: ClientOptions): Promise<T> {
  const method = opts.method ?? "GET";
  const url = buildUrl(opts.path, opts.query);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  if (opts.signal) {
    if (opts.signal.aborted) controller.abort();
    else opts.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Request-ID": newRequestId(),
  };
  if (!opts.anonymous) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: controller.signal,
    });
  } catch (error) {
    clearTimeout(timer);
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiClientError(0, "Request timed out");
    }
    throw new ApiClientError(0, "Network request failed");
  } finally {
    clearTimeout(timer);
  }

  const requestId = response.headers.get("X-Request-ID") || undefined;

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    if (shouldInvalidate(opts.path, response.status) && unauthorizedHandler) {
      unauthorizedHandler(opts.path);
    }
    const message = extractMessage(response.status, payload);
    const details =
      response.status === 422 ? (firstValidationMessage(payload) ?? undefined) : undefined;
    throw new ApiClientError(response.status, message, { requestId, details });
  }

  return payload as T;
}

function extractMessage(status: number, payload: unknown): string {
  if (payload !== null && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    // FastAPI may return {"detail": "..."} or {"detail": [{...}]} (422).
    if (typeof record.detail === "string" && record.detail) return record.detail;
    if (typeof record.message === "string" && record.message) return record.message;
    if (status === 422) {
      const first = firstValidationMessage(payload);
      if (first) return first;
    }
  }
  if (status === 401) return "Authentication required";
  if (status === 403) return "Forbidden";
  if (status === 429) return "Rate limit exceeded";
  if (status >= 500) return "Service failure";
  return "Request failed";
}

/** Convenience facade with the HTTP verbs. */
export const apiClient = {
  get: <T>(path: string, query?: ClientOptions["query"], opts?: Partial<ClientOptions>) =>
    apiRequest<T>({ ...opts, method: "GET", path, query }),
  post: <T>(path: string, body?: unknown, opts?: Partial<ClientOptions>) =>
    apiRequest<T>({ ...opts, method: "POST", path, body }),
  put: <T>(path: string, body?: unknown, opts?: Partial<ClientOptions>) =>
    apiRequest<T>({ ...opts, method: "PUT", path, body }),
  patch: <T>(path: string, body?: unknown, opts?: Partial<ClientOptions>) =>
    apiRequest<T>({ ...opts, method: "PATCH", path, body }),
  delete: <T>(path: string, opts?: Partial<ClientOptions>) =>
    apiRequest<T>({ ...opts, method: "DELETE", path }),
};
