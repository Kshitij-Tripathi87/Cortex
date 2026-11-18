import { describe, expect, it } from "vitest";
import { decisionTitle, describeDecisionOptions, describeOption, formatOptionValue } from "./decisionOptions";

const HOUSINGS = {
  decision_id: "01a1eed0-7caf-0007-082f-ded99feddb7c",
  situation: "Cast iron housings from S-101 are three weeks late.",
  recommended_option_id: "opt-b",
  options: [
    { option_id: "opt-a", label: "Expedite PO-5001 by air", expected_cost: 18400 },
    { option_id: "opt-b", label: "Move 250 units to Acme Metals", expected_cost: 9200 },
  ],
};

describe("describeOption", () => {
  it("names an option by the words recorded with it and lists the other fields", () => {
    expect(describeOption({ option_id: "opt-a", label: "Expedite PO-5001 by air", expected_cost: 18400 })).toEqual({
      id: "opt-a",
      name: "Expedite PO-5001 by air",
      hasDescription: true,
      details: [{ label: "expected cost", value: "18,400" }],
    });
  });

  it("reads the name from whichever naming field the caller used", () => {
    expect(describeOption({ id: 7, name: "Hold the order" }).name).toBe("Hold the order");
    expect(describeOption({ id: 7, name: "Hold the order" }).id).toBe("7");
    expect(describeOption({ option_id: "x", title: "Split the shipment" }).name).toBe("Split the shipment");
    expect(describeOption({ option_id: "x", action: "reroute_via_hamburg" }).name).toBe("reroute_via_hamburg");
    expect(describeOption({ option_id: "x", description: "Wait one week" }).name).toBe("Wait one week");
  });

  it("keeps a description as a detail when the option also has a label", () => {
    const option = describeOption({ option_id: "x", label: "Wait", description: "Do nothing for one week" });
    expect(option.name).toBe("Wait");
    expect(option.details).toEqual([{ label: "description", value: "Do nothing for one week" }]);
  });

  it("falls back to the identifier, then to the position, and says that it did", () => {
    const bare = describeOption({ option_id: "O1", nev: 100, sla: 0.95, cost: 50 });
    expect(bare.name).toBe("O1");
    expect(bare.hasDescription).toBe(false);
    expect(bare.details).toEqual([
      { label: "nev", value: "100" },
      { label: "sla", value: "0.95" },
      { label: "cost", value: "50" },
    ]);
    expect(describeOption({ cost: 50 }, 2)).toEqual({
      id: "",
      name: "Option 3",
      hasDescription: false,
      details: [{ label: "cost", value: "50" }],
    });
  });

  it("does not take an empty or non-text value for a name", () => {
    expect(describeOption({ option_id: "x", label: "  ", name: "Real name" }).name).toBe("Real name");
    expect(describeOption({ option_id: "x", label: 42 }).name).toBe("x");
    expect(describeOption({ option_id: "x", label: 42 }).details).toEqual([{ label: "label", value: "42" }]);
  });

  it("survives something that is not an object", () => {
    expect(describeOption(null, 0)).toEqual({ id: "", name: "Option 1", hasDescription: false, details: [] });
    expect(describeOption("free text" as unknown as Record<string, unknown>, 1).name).toBe("Option 2");
  });
});

describe("formatOptionValue", () => {
  it("shows a figure as recorded, with no unit added", () => {
    expect(formatOptionValue(18400)).toBe("18,400");
    expect(formatOptionValue(0.95)).toBe("0.95");
    expect(formatOptionValue(-3)).toBe("-3");
    expect(formatOptionValue("  21 days ")).toBe("21 days");
    expect(formatOptionValue(true)).toBe("yes");
    expect(formatOptionValue(false)).toBe("no");
  });

  it("leaves out what holds nothing", () => {
    for (const empty of [null, undefined, "", "   ", [], {}, Number.NaN]) {
      expect(formatOptionValue(empty)).toBe("");
    }
  });

  it("joins a plain list and keeps a nested record as written", () => {
    expect(formatOptionValue(["PO-5001", "PO-5002"])).toBe("PO-5001, PO-5002");
    expect(formatOptionValue({ carrier: "DHL", days: 3 })).toBe('{"carrier":"DHL","days":3}');
    expect(formatOptionValue([{ po: "PO-5001" }])).toBe('[{"po":"PO-5001"}]');
  });
});

describe("describeDecisionOptions", () => {
  it("names the recommended action in words, not by its identifier", () => {
    const view = describeDecisionOptions(HOUSINGS);
    expect(view.headlineKind).toBe("recommended");
    expect(view.headlineText).toBe("Move 250 units to Acme Metals");
    expect(view.headline?.id).toBe("opt-b");
    expect(view.options.map((option) => [option.name, option.recommended, option.chosen])).toEqual([
      ["Expedite PO-5001 by air", false, false],
      ["Move 250 units to Acme Metals", true, false],
    ]);
  });

  it("shows the identifier when the recommended option is not in the list", () => {
    const view = describeDecisionOptions({ recommended_option_id: "opt-z", options: HOUSINGS.options });
    expect(view.headline).toBeNull();
    expect(view.headlineText).toBe("opt-z");
    expect(view.options.some((option) => option.recommended)).toBe(false);
  });

  it("marks the chosen option, and leads with it only when nothing was recommended", () => {
    const both = describeDecisionOptions({ ...HOUSINGS, chosen_option: "opt-a" });
    expect(both.headlineKind).toBe("recommended");
    expect(both.headlineText).toBe("Move 250 units to Acme Metals");
    expect(both.options.map((option) => option.chosen)).toEqual([true, false]);

    const chosenOnly = describeDecisionOptions({ options: HOUSINGS.options, chosen_option: "opt-a" });
    expect(chosenOnly.headlineKind).toBe("chosen");
    expect(chosenOnly.headlineText).toBe("Expedite PO-5001 by air");
  });

  it("says so when the decision records neither", () => {
    const view = describeDecisionOptions({ options: [{ option_id: "O1" }] });
    expect(view.headlineKind).toBe("none");
    expect(view.headlineText).toBe("None recorded");
    expect(view.headline).toBeNull();
  });

  it("accepts a decision without options", () => {
    for (const decision of [null, undefined, {}, { options: null }, { options: [] }]) {
      expect(describeDecisionOptions(decision).options).toEqual([]);
    }
    expect(describeDecisionOptions({ recommended_option_id: "O1" }).headlineText).toBe("O1");
  });
});

describe("decisionTitle", () => {
  it("is the situation the decision is about", () => {
    expect(decisionTitle(HOUSINGS)).toBe("Cast iron housings from S-101 are three weeks late.");
  });

  it("is the recommended option when no situation was recorded", () => {
    expect(decisionTitle({ ...HOUSINGS, situation: "  " })).toBe("Move 250 units to Acme Metals");
  });

  it("is the identifier when there are no words at all", () => {
    expect(decisionTitle({ decision_id: "d-1", recommended_option_id: "O1", options: [{ option_id: "O1" }] })).toBe("d-1");
    expect(decisionTitle({ decision_id: "d-1" })).toBe("d-1");
    expect(decisionTitle(null)).toBe("Decision");
  });
});
