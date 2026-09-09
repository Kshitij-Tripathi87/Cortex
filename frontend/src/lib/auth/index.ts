/** B2 auth library barrel. Pages import from "@/lib/auth". */

export { AuthProvider, useAuth } from "./AuthProvider";
export type { AuthStatus, AuthUser, AuthWorkspace, AuthOrganization } from "./AuthProvider";
export { RequireAuth, RequireAnonymous, AuthChecking } from "./guards";
export { apiClient, apiRequest, resolveApiBase, setUnauthorizedHandler } from "./client";
export { ApiClientError, isApiClientError, authFormMessage, kindForStatus } from "./errors";
export type { ApiErrorKind } from "./errors";
export { getToken, setToken, clearToken, subscribeTokenChanges, getOnboardingAck, setOnboardingAck } from "./token";
export { sanitizeNext } from "./next";
export {
  emailSchema,
  passwordSchema,
  loginSchema,
  signupSchema,
  forgotPasswordSchema,
  resetPasswordSchema,
  changePasswordSchema,
  toFieldErrors,
} from "./validation";
export type { FieldErrors } from "./validation";
export type {
  MeResponse,
  LoginResponse,
  SignupRequest,
  LoginRequest,
  AuthSnapshot,
} from "./types";
