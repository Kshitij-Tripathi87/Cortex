/**
 * Public contact and demo requests.
 *
 * The site has no mailbox behind it. A request is saved by
 * POST /api/v1/public/contact-requests and the reference shown to the visitor
 * is the one the server stored, so "your request was received" is only ever
 * said about something that really was saved.
 */

import { apiRequest } from "@/lib/auth/client";
import { isApiClientError } from "@/lib/auth/errors";

export const CONTACT_TOPICS = [
  { value: "general", label: "General question" },
  { value: "sales", label: "Sales and deployment" },
  { value: "engineering", label: "Engineering and research" },
  { value: "security", label: "Security report" },
  { value: "privacy", label: "Privacy request" },
  { value: "legal", label: "Legal" },
] as const;

export type ContactTopic = (typeof CONTACT_TOPICS)[number]["value"] | "demo";

/** Topics a visitor can pick on the contact form ("demo" has its own form). */
export function isSelectableTopic(value: string | null | undefined): value is ContactTopic {
  return CONTACT_TOPICS.some((topic) => topic.value === value);
}

export interface DemoRequestDetails {
  job_title?: string;
  primary_role?: string;
  country?: string;
  company_size?: string;
  challenges?: string[];
  current_systems?: string[];
  desired_outcome?: string;
  timeline?: string;
}

export interface ContactRequestPayload {
  topic: ContactTopic;
  full_name: string;
  email: string;
  company?: string;
  message: string;
  consent: boolean;
  details?: DemoRequestDetails;
}

export interface ContactRequestReceipt {
  reference: string;
  received_at: string;
}

/** Limits enforced by the server; mirrored here so the form can say so early. */
export const CONTACT_LIMITS = {
  name: 200,
  email: 320,
  company: 200,
  message: 4000,
} as const;

function clean(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

export async function submitContactRequest(
  payload: ContactRequestPayload,
): Promise<ContactRequestReceipt> {
  const details = payload.details
    ? {
        job_title: clean(payload.details.job_title),
        primary_role: clean(payload.details.primary_role),
        country: clean(payload.details.country),
        company_size: clean(payload.details.company_size),
        challenges: payload.details.challenges ?? [],
        current_systems: payload.details.current_systems ?? [],
        desired_outcome: clean(payload.details.desired_outcome),
        timeline: clean(payload.details.timeline),
      }
    : undefined;
  const receipt = await apiRequest<ContactRequestReceipt>({
    method: "POST",
    path: "/public/contact-requests",
    anonymous: true,
    body: {
      topic: payload.topic,
      full_name: payload.full_name.trim(),
      email: payload.email.trim(),
      company: clean(payload.company),
      message: payload.message.trim(),
      consent: payload.consent,
      details,
    },
  });
  // Never show a made-up reference: without one from the server, the request
  // is treated as not saved.
  if (!receipt || typeof receipt.reference !== "string" || receipt.reference.length === 0) {
    throw new Error("The server did not confirm the request");
  }
  return receipt;
}

/** What to tell the visitor when a request could not be saved. */
export function contactRequestErrorMessage(error: unknown): string {
  const notSaved = "Your request was not saved.";
  if (isApiClientError(error)) {
    switch (error.kind) {
      case "validation":
        return typeof error.details === "string" && error.details
          ? `${notSaved} Please check the form: ${error.details}`
          : `${notSaved} Please check the form and try again.`;
      case "rate_limited":
        return `${notSaved} Too many requests were sent from this network. Please try again in an hour.`;
      case "network":
        return `${notSaved} We could not reach the server. Check your connection and try again.`;
      case "server":
        return `${notSaved} Something went wrong on our side. Please try again in a moment.`;
      default:
        return `${notSaved} Please try again.`;
    }
  }
  return `${notSaved} Please try again.`;
}
