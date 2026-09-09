/**
 * B2 auth domain types — mirrors backend/app/api/v1/auth.py contracts.
 * Auth state is always derived from GET /auth/me, never from client claims.
 */

export interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthWorkspace {
  id: string;
  name: string;
  slug: string;
}

export interface AuthOrganization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  trial_ends_at: string | null;
}

export interface MeResponse {
  user: AuthUser;
  workspace: AuthWorkspace;
  organization: AuthOrganization | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user_id: string;
  workspace_id: string;
  role: string;
  organization_id: string | null;
}

export interface SignupRequest {
  organization_name: string;
  workspace_name?: string;
  email: string;
  password: string;
  full_name?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  /** Optional strict scoping; omitted in normal UX (email is globally unique). */
  workspace_id?: string;
}

export type AuthStatus = "UNKNOWN" | "CHECKING" | "AUTHENTICATED" | "ANONYMOUS";

export interface AuthSnapshot {
  status: AuthStatus;
  user: AuthUser | null;
  workspace: AuthWorkspace | null;
  organization: AuthOrganization | null;
  /** Last boot/refresh failure (network or unexpected); 401s are not errors. */
  error: string | null;
}
