/**
 * API client for Cortex backend.
 * Base URL configured via NEXT_PUBLIC_API_URL environment variable
 * (defaults to http://localhost:8000, the FastAPI host).
 *
 * Paths passed to api.get/post/etc. may be either:
 *   - "/sources/upload"           → resolved to <base>/api/v1/sources/upload
 *   - "/api/v1/graph/nodes"       → resolved to <base>/api/v1/graph/nodes
 * The duplicate-prefix bug (e.g. <base>/api/v1/api/v1/graph/...) is prevented
 * by only prepending "/api/v1" when the path does not already include it.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Raw backend origin — for non-fetch channels (EventSource, WebSocket). */
export const apiBaseUrl = API_BASE_URL;
const TOKEN_STORAGE_KEY = "cortex:access_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public requestId?: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

interface FetchOptions extends RequestInit {
  params?: Record<string, string | number | boolean | string[] | undefined>;
}

function buildUrl(path: string, params?: FetchOptions["params"]): string {
  // Avoid double-prefixing /api/v1 when the caller already includes it.
  const fullPath = path.startsWith("/api/") ? path : `/api/v1${path}`;
  const url = new URL(`${API_BASE_URL}${fullPath}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) continue;
      if (Array.isArray(value)) {
        url.searchParams.set(key, value.join(","));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

function getAuthHeader(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const token = localStorage.getItem(TOKEN_STORAGE_KEY);
  return token ? `Bearer ${token}` : undefined;
}

export function setAuthToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export async function apiFetch<T>(
  path: string,
  options: FetchOptions = {},
): Promise<T> {
  const { params, headers, ...rest } = options;
  const url = buildUrl(path, params);

  const authHeader = getAuthHeader();
  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (headers) {
    // Normalize headers to Record<string, string>
    if (Array.isArray(headers)) {
      for (const [key, value] of headers) {
        requestHeaders[key] = value;
      }
    } else if (headers instanceof Headers) {
      headers.forEach((value, key) => {
        requestHeaders[key] = value;
      });
    } else {
      Object.assign(requestHeaders, headers);
    }
  }
  if (authHeader) {
    requestHeaders["Authorization"] = authHeader;
  }

  const response = await fetch(url, {
    ...rest,
    headers: requestHeaders,
  });

  if (!response.ok) {
    let detail = "An error occurred";
    let requestId: string | undefined;
    try {
      const body = await response.json();
      detail = body.detail || body.message || detail;
    } catch {
      // Non-JSON response
    }
    requestId = response.headers.get("X-Request-ID") || undefined;
    throw new ApiError(response.status, detail, requestId);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string, params?: FetchOptions["params"]) =>
    apiFetch<T>(path, { method: "GET", params }),

  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    }),

  put: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: "PUT",
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
