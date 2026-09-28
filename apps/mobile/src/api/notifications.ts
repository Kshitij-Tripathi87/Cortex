/**
 * Notifications â€” push registration + durable state (Day 25 Â§15/Â§19).
 *
 * The notification policy lives server-side: only operationally significant
 * events (TASK_COMPLETED / TASK_FAILED / TASK_BLOCKED / APPROVAL_REQUIRED /
 * DEVICE_OFFLINE / DEVICE_RECONNECTED / IMPORTANT_RESULT) fan out; ordinary
 * agent/tool noise never reaches the phone.
 */

import { apiGet, apiPost, unwrap } from "./client.ts";

export interface PushRegistration {
  registration_id: string;
  device_id: string;
  provider: string;
  active: boolean;
}

export interface NotificationRecord {
  notification_id: string;
  event_type: string;
  title: string;
  body: string | null;
  delivered_via: string;
  delivered_at: string;
  read_at: string | null;
}

export async function registerPush(
  deviceId: string,
  pushToken: string,
  provider = "fcm",
): Promise<PushRegistration> {
  return unwrap(
    await apiPost<{ data: PushRegistration }>("/mobile/push/register", {
      device_id: deviceId,
      provider,
      push_token: pushToken,
    }),
  );
}

export async function listNotifications(limit = 50): Promise<NotificationRecord[]> {
  const body = await apiGet<{ data: { notifications: NotificationRecord[]; count: number } }>(
    "/mobile/notifications",
    { params: { limit } },
  );
  return body.data.notifications;
}
