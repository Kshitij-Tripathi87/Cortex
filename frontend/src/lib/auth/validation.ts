/**
 * Form schemas (B2 §4–§5). Client-side mirrors of the server policy so users
 * get instant feedback; the SERVER remains the authority (422s are mapped
 * through ApiClientError, never trusted blindly).
 */

import { z } from "zod";

export const emailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .min(3, "Enter your email address.")
  .max(320, "Email is too long.")
  .email("Enter a valid email address.");

/** Mirrors backend: >= 10 chars with at least one letter and one digit. */
export const passwordSchema = z
  .string()
  .min(10, "Password must be at least 10 characters.")
  .max(128, "Password must be at most 128 characters.")
  .regex(/[A-Za-z]/, "Password must include a letter.")
  .regex(/\d/, "Password must include a digit.");

export const loginSchema = z.object({
  email: emailSchema,
  // Login passwords are not policy-checked client-side: any string is
  // submitted and the server answers with its generic 401 (no oracle).
  password: z.string().min(1, "Enter your password."),
});

export const signupSchema = z
  .object({
    fullName: z.string().trim().min(1, "Enter your name.").max(256, "Name is too long."),
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string().min(1, "Confirm your password."),
    organizationName: z
      .string()
      .trim()
      .min(2, "Organization name must be at least 2 characters.")
      .max(256, "Organization name is too long."),
    workspaceName: z
      .string()
      .trim()
      .max(256, "Workspace name is too long.")
      .optional()
      .transform((value) => (value && value.length > 0 ? value : undefined)),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export const forgotPasswordSchema = z.object({
  email: emailSchema,
});

export const resetPasswordSchema = z
  .object({
    token: z.string().min(20, "This reset link is incomplete."),
    newPassword: passwordSchema,
    confirmPassword: z.string().min(1, "Confirm your new password."),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Enter your current password."),
    newPassword: passwordSchema,
    confirmPassword: z.string().min(1, "Confirm your new password."),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  })
  .refine((data) => data.newPassword !== data.currentPassword, {
    message: "New password must differ from the current one.",
    path: ["newPassword"],
  });

export type FieldErrors = Record<string, string>;

/** Flatten a Zod safeParse failure into per-field messages. */
export function toFieldErrors(error: z.ZodError): FieldErrors {
  const out: FieldErrors = {};
  for (const issue of error.issues) {
    const key = issue.path.length > 0 ? String(issue.path[0]) : "_form";
    if (!(key in out)) out[key] = issue.message;
  }
  return out;
}
