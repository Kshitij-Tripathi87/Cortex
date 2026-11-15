/**
 * Authentication â€” login/refresh/logout + secure device storage (Day 25 Â§3).
 *
 * Flow: Login -> Vanessa Auth -> short-lived access token -> secure device
 * storage. Never ship permanent backend credentials inside the app.
 *
 * The storage layer is abstracted: SecureStore (react-native-keychain) on
 * device, AsyncStorage/AsyncStorage-like KV in tests â€” the auth flow and
 * the reconnection contract are storage-independent.
 */

import { apiPost, unwrap } from "./client.ts";

export interface AuthIdentity {
  email: string;
  password: string;
  accessToken: string;
  refreshToken: string | null;
  workspaceId: string;
  userId: string;
}

/** Minimal KV contract â€” implemented by SecureStore/KV on each platform. */
export interface TokenStorage {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  clear(): Promise<void>;
}

const TOKEN_KEY = "vanessa:access_token";

export async function loadStoredToken(storage: TokenStorage): Promise<string | null> {
  return storage.get(TOKEN_KEY);
}

export async function persistToken(
  storage: TokenStorage,
  accessToken: string,
): Promise<void> {
  await storage.set(TOKEN_KEY, accessToken);
}

export async function clearStoredToken(storage: TokenStorage): Promise<void> {
  await storage.clear();
}

interface SignupResponse {
  access_token: string;
  workspace_id: string;
  user_id: string;
}

export async function signup(
  organizationName: string,
  email: string,
  password: string,
  fullName: string,
): Promise<AuthIdentity> {
  const body = await apiPost<SignupResponse>("/auth/signup", {
    organization_name: organizationName,
    email,
    password,
    full_name: fullName,
  });
  return {
    email,
    password,
    accessToken: body.access_token,
    refreshToken: null,
    workspaceId: body.workspace_id,
    userId: body.user_id,
  };
}

export async function login(email: string, password: string): Promise<AuthIdentity> {
  const body = await apiPost<SignupResponse>("/auth/login", { email, password });
  return {
    email,
    password,
    accessToken: body.access_token,
    refreshToken: null,
    workspaceId: body.workspace_id,
    userId: body.user_id,
  };
}

/** Reconnection step 1: refresh the token when required. */
export async function refreshAuth(
  identity: AuthIdentity,
): Promise<AuthIdentity> {
  const body = await apiPost<SignupResponse>("/auth/login", {
    email: identity.email,
    password: identity.password,
  });
  return { ...identity, accessToken: body.access_token };
}
