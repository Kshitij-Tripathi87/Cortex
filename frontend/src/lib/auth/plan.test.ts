import { describe, expect, it } from "vitest";
import { PLAN_CONTACT_HREF, formatDay, planStatus } from "./plan";

// The site prints days in the visitor's own time zone. Pin one here so the
// expected text does not depend on where the tests run.
process.env.TZ = "UTC";

const NOW = new Date("2026-11-18T12:00:00Z");
const EARLY = new Date("2026-11-18T00:30:00Z");

function org(plan: string, trialEndsAt: string | null, active?: boolean) {
  return { plan, trial_ends_at: trialEndsAt, subscription_active: active };
}

describe("planStatus", () => {
  it("says how long a running trial has left", () => {
    expect(planStatus(org("trial", "2026-11-25T12:00:00Z", true), NOW)).toEqual({
      label: "Trial",
      detail: "7 days left, ends 25 Nov 2026",
      paused: false,
      pausedReason: null,
    });
    // A part of a day counts as a day, as on the onboarding page: 2 days 11.5 hours.
    expect(planStatus(org("trial", "2026-11-20T12:00:00Z", true), EARLY)?.detail).toBe(
      "3 days left, ends 20 Nov 2026",
    );
  });

  it("writes one day in the singular", () => {
    expect(planStatus(org("trial", "2026-11-19T12:00:00Z", true), NOW)?.detail).toBe(
      "1 day left, ends 19 Nov 2026",
    );
  });

  it("does not round the last hours of a trial up to a day", () => {
    expect(planStatus(org("trial", "2026-11-18T12:00:00Z", true), EARLY)?.detail).toBe(
      "less than a day left, ends 18 Nov 2026",
    );
  });

  it("says a trial has ended when the server says so, with the day it ended", () => {
    expect(planStatus(org("trial", "2026-11-10T12:00:00Z", false), NOW)).toEqual({
      label: "Trial ended",
      detail: "on 10 Nov 2026",
      paused: true,
      pausedReason: "Your trial ended on 10 Nov 2026.",
    });
  });

  it("takes the server's word, not the browser clock, for whether the trial ended", () => {
    // The browser clock is a week fast: the end date looks past, the server says active.
    const fastClock = new Date("2026-11-30T12:00:00Z");
    const running = planStatus(org("trial", "2026-11-25T12:00:00Z", true), fastClock);
    expect(running?.paused).toBe(false);
    expect(running?.label).toBe("Trial");
    expect(running?.detail).toBe("ends 25 Nov 2026");

    // The browser clock is a week slow: the end date looks ahead, the server says ended.
    const slowClock = new Date("2026-11-03T12:00:00Z");
    const ended = planStatus(org("trial", "2026-11-10T12:00:00Z", false), slowClock);
    expect(ended?.paused).toBe(true);
    expect(ended?.label).toBe("Trial ended");
  });

  it("does not announce an ended plan when the API does not send the verdict", () => {
    const status = planStatus(org("trial", "2026-11-10T12:00:00Z", undefined), NOW);
    expect(status?.paused).toBe(false);
    expect(status?.pausedReason).toBeNull();
  });

  it("names the plans that do not end, without a trial date", () => {
    expect(planStatus(org("pro", "2026-11-10T12:00:00Z", true), NOW)).toEqual({
      label: "Pro plan",
      detail: "",
      paused: false,
      pausedReason: null,
    });
    expect(planStatus(org("free", null, true), NOW)?.label).toBe("Free plan");
    expect(planStatus(org("enterprise", null, true), NOW)?.label).toBe("Enterprise plan");
  });

  it("handles a trial without an end date and an unknown plan", () => {
    expect(planStatus(org("trial", null, true), NOW)).toMatchObject({
      label: "Trial",
      detail: "no end date",
      paused: false,
    });
    expect(planStatus(org("trial", null, false), NOW)).toMatchObject({
      label: "Trial ended",
      detail: "",
      pausedReason: "Your trial has ended.",
    });
    expect(planStatus(org("starter", null, false), NOW)).toEqual({
      label: 'Plan "starter"',
      detail: "not active",
      paused: true,
      pausedReason: "Your plan is not active.",
    });
  });

  it("returns nothing without an organization", () => {
    expect(planStatus(null, NOW)).toBeNull();
    expect(planStatus(undefined, NOW)).toBeNull();
  });
});

describe("formatDay", () => {
  it("prints a day that cannot be misread as month/day", () => {
    expect(formatDay("2026-11-10T12:00:00Z")).toBe("10 Nov 2026");
    expect(formatDay("2026-03-04T12:00:00Z")).toBe("4 Mar 2026");
  });

  it("returns nothing for a missing or broken date", () => {
    expect(formatDay(null)).toBeNull();
    expect(formatDay("")).toBeNull();
    expect(formatDay("not a date")).toBeNull();
  });
});

describe("where a paused user is sent", () => {
  it("is the contact form with the sales topic chosen", () => {
    expect(PLAN_CONTACT_HREF).toBe("/contact?topic=sales#write");
  });
});
