/**
 * Auth API — B1 contract (v0.8.5-B1/B2). Thin typed wrappers over the
 * centralized client; session semantics live in AuthProvider.
 *
 *   POST /auth/signup | POST /auth/login | GET /auth/me | POST /auth/logout
 *   POST /auth/change-password | POST /auth/reset/request | POST /auth/reset/confirm
 */

import { apiClient } from "@/lib/auth/client";
import type { LoginRequest, LoginResponse, MeResponse, SignupRequest } from "@/lib/auth/types";

export async function signup(payload: SignupRequest): Promise<LoginResponse> {
  return apiClient.post<LoginResponse>("/auth/signup", payload, { anonymous: true });
}

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  return apiClient.post<LoginResponse>("/auth/login", payload, { anonymous: true });
}

export async function fetchCurrentUser(): Promise<MeResponse> {
  return apiClient.get<MeResponse>("/auth/me");
}

export async function logout(): Promise<{ success: boolean }> {
  return apiClient.post<{ success: boolean }>("/auth/logout");
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await apiClient.post("/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export interface ResetRequestResult {
  requested: boolean;
  /** Present only when the backend runs in dev/test. Never rendered. */
  reset_token: string | null;
}

export async function requestPasswordReset(email: string): Promise<ResetRequestResult> {
  return apiClient.post<ResetRequestResult>("/auth/reset/request", { email }, { anonymous: true });
}

export async function confirmPasswordReset(token: string, newPassword: string): Promise<void> {
  await apiClient.post(
    "/auth/reset/confirm",
    { token, new_password: newPassword },
    { anonymous: true },
  );
}
