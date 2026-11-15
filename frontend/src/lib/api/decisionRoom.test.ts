/**
 * Decision Room typed API client — URL/body construction and error mapping.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/auth/errors";
import { decideTaskApproval, fetchDecisionRoom } from "./decisionRoom";

const VIEW = {
  task: {
    task_id: "t-1",
    trace_id: "tr-1",
    status: "AWAITING_APPROVAL",
    objective: "Adjust stock",
    world_state_version: 1,
    budget: 100,
    deadline: null,
    requires_approval: true,
  },
  pending_decision: {
    awaited_since: "2026-09-20T00:00:00+00:00",
    reason: "Consequential governance",
    approval_required_for: ["world.inventory.adjust"],
    consequential_proposals: [],
    evidence_refs: [],
  },
  recommendation: null,
  plan: null,
  runs: [],
  steps: [],
  invocations: [],
  evidence: [],
  proposals: [],
  policy_results: [],
  approvals: [],
  execution: null,
  outcome: null,
  consequential_capabilities: [],
};

function envelope(data: unknown) {
  return { request_id: "req-1", correlation_id: null, timestamp: "2026-09-20T00:00:00Z", data };
}

function stubFetch(handler: (url: string, init: RequestInit) => Response): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL | Request, init: RequestInit = {}) =>
      handler(String(url), init)
    )
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchDecisionRoom", () => {
  it("requests the canonical decision-room surface with workspace scoping", async () => {
    let seenUrl = "";
    stubFetch((url) => {
      seenUrl = url;
      return new Response(JSON.stringify(envelope({ decision_room: VIEW })), { status: 200 });
    });

    const response = await fetchDecisionRoom("t 1", "ws-1");
    expect(seenUrl).toContain("/api/v1/nexus/tasks/t%201/decision-room");
    expect(seenUrl).toContain("workspace_id=ws-1");
    expect(response.data.decision_room.task.status).toBe("AWAITING_APPROVAL");
    expect(response.data.decision_room.pending_decision?.approval_required_for).toEqual([
      "world.inventory.adjust",
    ]);
  });

  it("maps 404 to ApiClientError", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "task not found" }), { status: 404 }));
    await expect(fetchDecisionRoom("missing", "ws-1")).rejects.toMatchObject({
      status: 404,
    } satisfies Partial<ApiClientError>);
  });
});

describe("decideTaskApproval", () => {
  it("posts the server-enforced decision body", async () => {
    let seenUrl = "";
    let seenBody: unknown = null;
    stubFetch((url, init) => {
      seenUrl = url;
      seenBody = JSON.parse(String(init.body));
      return new Response(JSON.stringify(envelope({ task_id: "t-1", status: "APPROVED", approved: true })), {
        status: 200,
      });
    });

    const response = await decideTaskApproval({
      taskId: "t-1",
      workspaceId: "ws-1",
      approved: true,
      reason: "reviewed",
    });
    expect(seenUrl).toContain("/api/v1/nexus/tasks/t-1/approvals");
    expect(seenBody).toEqual({
      workspace_id: "ws-1",
      approved: true,
      reason: "reviewed",
    });
    expect(response.data.status).toBe("APPROVED");
  });

  it("omits empty reason and maps 403 denial to ApiClientError", async () => {
    let seenBody: unknown = null;
    stubFetch((_, init) => {
      seenBody = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ detail: "Permission denied" }), { status: 403 });
    });

    await expect(
      decideTaskApproval({ taskId: "t-1", workspaceId: "ws-1", approved: false })
    ).rejects.toMatchObject({ status: 403 } satisfies Partial<ApiClientError>);
    expect(seenBody).toEqual({ workspace_id: "ws-1", approved: false });
  });
});
