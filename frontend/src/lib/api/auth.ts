/**
 * Cortex Nexus — Identity & Auth Typed API Client (Track X2)
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

export interface LoginRequest {
  email: string;
  password?: string;
  tenant_id?: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: {
    id: string;
    email: string;
    role: string;
    organization_id: string;
    capabilities: string[];
  };
}

export async function login(req: LoginRequest): Promise<AuthResponse> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) throw new Error("Authentication failed");
  return resp.json();
}

export async function logout(): Promise<{ success: boolean }> {
  const resp = await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
  if (!resp.ok) throw new Error("Logout failed");
  return resp.json();
}

export async function fetchCurrentUser(): Promise<AuthResponse["user"]> {
  const resp = await fetch(`${API_BASE}/auth/me`, { cache: "no-store" });
  if (!resp.ok) throw new Error("Failed to fetch current user");
  return resp.json();
}
