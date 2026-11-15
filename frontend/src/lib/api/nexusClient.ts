/**
 * Cortex Nexus — canonical assistant client (spec §8).
 *
 * Talks to the canonical, tenant-scoped `POST /nexus/vanessa/ask`.
 *
 * The previous implementation called the unauthenticated `/workspace/query/*`
 * demo singleton. That path is retired: it carried no auth, hardcoded
 * `ws_default`/`org_default`, and kept state in process memory, so any
 * UI-driven answer bypassed tenant isolation (RC0: tenancy must be
 * server-derived, and no canonical route may read demo state).
 *
 * The canonical response exposes only what the server actually derived:
 * rendered text, the classified intent, the tools that ran, and the grounded
 * evidence records. It deliberately exposes no synthesised confidence score,
 * checksum, or ROI figure — those were demo-only decoration, and
 * Instructions.md.txt §5 / SPEC-000170 forbid invented metrics.
 */

import { request } from "./http";

/** `data` payload of the canonical /nexus/vanessa/ask envelope. */
export interface VanessaResponse {
  response: string;
  intent: string;
  actions_taken: string[];
  evidence: Array<Record<string, unknown>>;
  permission_denied: string | null;
  trace_id: string;
  world_state_version: number | null;
}

interface VanessaEnvelope {
  request_id: string;
  correlation_id: string | null;
  timestamp: string;
  data: VanessaResponse;
}

/**
 * Ask the canonical assistant. `workspaceId` is sent as a query parameter so
 * the server can run its own `require_workspace_access` check — the client
 * never asserts tenancy, it only names the scope it is asking about.
 */
export async function askVanessa(
  workspaceId: string,
  query: string,
): Promise<VanessaResponse> {
  const envelope = await request<VanessaEnvelope>({
    method: "POST",
    path: "/nexus/vanessa/ask",
    query: { workspace_id: workspaceId },
    body: { query },
  });
  return envelope.data;
}
