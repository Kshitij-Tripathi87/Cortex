/**
 * Decision Room UI gating — role rules and presentation mapping.
 */

import { describe, expect, it } from "vitest";

import {
  canApproveDecision,
  invocationStatusBadgeClass,
  taskStatusBadgeClass,
} from "./decisionRoomModel";

describe("canApproveDecision", () => {
  it("allows operator and admin roles", () => {
    expect(canApproveDecision("operator")).toBe(true);
    expect(canApproveDecision("admin")).toBe(true);
  });

  it("denies viewer, analyst, and unknown roles", () => {
    expect(canApproveDecision("viewer")).toBe(false);
    expect(canApproveDecision("analyst")).toBe(false);
    expect(canApproveDecision("system_admin")).toBe(false);
    expect(canApproveDecision("")).toBe(false);
  });

  it("denies missing identity", () => {
    expect(canApproveDecision(null)).toBe(false);
    expect(canApproveDecision(undefined)).toBe(false);
  });
});

describe("taskStatusBadgeClass", () => {
  it("maps terminal and lifecycle states to distinct presentations", () => {
    expect(taskStatusBadgeClass("COMPLETED")).toContain("emerald");
    expect(taskStatusBadgeClass("AWAITING_APPROVAL")).toContain("amber");
    expect(taskStatusBadgeClass("APPROVED")).toContain("blue");
    expect(taskStatusBadgeClass("EXECUTING")).toContain("blue");
    expect(taskStatusBadgeClass("FAILED")).toContain("red");
    expect(taskStatusBadgeClass("BLOCKED")).toContain("red");
    expect(taskStatusBadgeClass("REJECTED")).toContain("red");
  });

  it("falls back to neutral for unknown states", () => {
    expect(taskStatusBadgeClass("MYSTERY")).toContain("zinc");
  });
});

describe("invocationStatusBadgeClass", () => {
  it("maps invocation outcomes", () => {
    expect(invocationStatusBadgeClass("SUCCESS")).toContain("emerald");
    expect(invocationStatusBadgeClass("BLOCKED")).toContain("amber");
    expect(invocationStatusBadgeClass("FAILED")).toContain("red");
    expect(invocationStatusBadgeClass("OTHER")).toContain("zinc");
  });
});
