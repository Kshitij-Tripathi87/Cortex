import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tokenMock = vi.hoisted(() => ({
  getToken: vi.fn<() => string | null>(),
}));

vi.mock("./token", () => ({
  getToken: tokenMock.getToken,
}));

import { apiRequest } from "./client";

describe("apiRequest request-body handling", () => {
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

  beforeEach(() => {
    tokenMock.getToken.mockReturnValue("demo-jwt");
    fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ accepted: true }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("sends FormData unchanged, includes Bearer auth, and leaves multipart boundary to the browser", async () => {
    const formData = new FormData();
    formData.append("workspace_id", "workspace-123");
    formData.append("source_system_hint", "erp");
    formData.append("file", new Blob(["supplier_id,name\nS-1,Acme"], { type: "text/csv" }), "suppliers.csv");

    const result = await apiRequest<{ accepted: boolean }>({
      method: "POST",
      path: "/sources/upload",
      body: formData,
    });

    const [url, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init.headers);

    expect(String(url)).toContain("/sources/upload");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(formData);
    expect(headers.get("Authorization")).toBe("Bearer demo-jwt");
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("X-Request-ID")).toBeTruthy();
    expect(result).toEqual({ accepted: true });
  });

  it("continues to serialize JSON requests with the JSON content type", async () => {
    const body = { workspace_id: "workspace-123", state: "ready" };

    await apiRequest({
      method: "POST",
      path: "/nexus/observations",
      body,
    });

    const [, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit];
    const headers = new Headers(init.headers);

    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify(body));
    expect(headers.get("Authorization")).toBe("Bearer demo-jwt");
  });
});
