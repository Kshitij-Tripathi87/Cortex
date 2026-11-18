/**
 * The options of a decision, in words.
 *
 * A decision stores its options as the caller wrote them: free-form objects.
 * The Decision Room is where a person approves one of them, so the page has
 * to say what each option is. It printed the objects as JSON and named the
 * recommended action by its identifier ("opt-b").
 *
 * Nothing is interpreted here. A figure is shown as it was recorded, under the
 * name of its field, without a unit or a currency the record does not state.
 */

export type DecisionOption = Record<string, unknown>;

export interface OptionDetail {
  label: string;
  value: string;
}

export interface DescribedOption {
  /** What the decision calls the option (`recommended_option_id` refers to it); "" when it has none. */
  id: string;
  /** The option in the words recorded with it; its identifier or position when there are none. */
  name: string;
  /** False when `name` is only an identifier or a position in the list. */
  hasDescription: boolean;
  /** Every other field recorded with the option. */
  details: OptionDetail[];
}

export interface ListedOption extends DescribedOption {
  recommended: boolean;
  chosen: boolean;
}

export interface DecisionOptionsView {
  /** Identifier the decision recommends; "" when none is recorded. */
  recommendedId: string;
  /** Identifier recorded as chosen; "" when none is recorded. */
  chosenId: string;
  /** The option the heading names: the recommended one, or the chosen one when nothing was recommended. */
  headline: ListedOption | null;
  /** "recommended", "chosen", or "none" when the decision records neither. */
  headlineKind: "recommended" | "chosen" | "none";
  /** Heading text: the option's words, its identifier when it is not in the list, or a plain statement. */
  headlineText: string;
  options: ListedOption[];
}

interface DecisionLike {
  decision_id?: string | null;
  situation?: string | null;
  options?: DecisionOption[] | null;
  recommended_option_id?: string | null;
  chosen_option?: string | null;
}

// Tried in order. An identifier is what `recommended_option_id` refers to; a
// name is the first field that holds the option in words.
const ID_FIELDS = ["option_id", "id"] as const;
const NAME_FIELDS = ["label", "name", "title", "action", "summary", "description"] as const;

function text(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return "";
}

function fieldLabel(key: string): string {
  return key.replace(/[_\s]+/g, " ").trim();
}

/** A recorded value as text; "" when there is nothing to show. */
export function formatOptionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toLocaleString("en-IN", { maximumFractionDigits: 6 }) : "";
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    const scalars = value.every((item) => item === null || ["string", "number", "boolean"].includes(typeof item));
    if (scalars) {
      return value
        .map((item) => formatOptionValue(item))
        .filter((item) => item !== "")
        .join(", ");
    }
  }
  if (typeof value === "object" && Object.keys(value as object).length === 0) return "";
  // A nested record is shown as written rather than left out.
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** One option as a name, an identifier and the remaining fields. */
export function describeOption(option: DecisionOption | null | undefined, index = 0): DescribedOption {
  const record: DecisionOption = option && typeof option === "object" && !Array.isArray(option) ? option : {};
  const idField = ID_FIELDS.find((field) => text(record[field]) !== "");
  const nameField = NAME_FIELDS.find((field) => typeof record[field] === "string" && text(record[field]) !== "");
  const id = idField ? text(record[idField]) : "";
  const details: OptionDetail[] = [];
  for (const [key, value] of Object.entries(record)) {
    if (key === idField || key === nameField) continue;
    const shown = formatOptionValue(value);
    if (shown !== "") details.push({ label: fieldLabel(key), value: shown });
  }
  return {
    id,
    name: nameField ? text(record[nameField]) : id || `Option ${index + 1}`,
    hasDescription: nameField !== undefined,
    details,
  };
}

/** The options of a decision, with the recommended and the chosen one marked. */
export function describeDecisionOptions(decision: DecisionLike | null | undefined): DecisionOptionsView {
  const recommendedId = text(decision?.recommended_option_id);
  const chosenId = text(decision?.chosen_option);
  const options: ListedOption[] = (Array.isArray(decision?.options) ? decision.options : []).map((option, index) => {
    const described = describeOption(option, index);
    return {
      ...described,
      recommended: recommendedId !== "" && described.id === recommendedId,
      chosen: chosenId !== "" && described.id === chosenId,
    };
  });

  const headlineKind = recommendedId ? "recommended" : chosenId ? "chosen" : "none";
  const headlineId = recommendedId || chosenId;
  const headline = headlineId ? (options.find((option) => option.id === headlineId) ?? null) : null;
  const headlineText = headline ? headline.name : headlineId || "None recorded";
  return { recommendedId, chosenId, headline, headlineKind, headlineText, options };
}

/** What a decision is about, for a list: its situation, else its recommended option, else its identifier. */
export function decisionTitle(decision: DecisionLike | null | undefined): string {
  const situation = text(decision?.situation);
  if (situation) return situation;
  const view = describeDecisionOptions(decision);
  if (view.headline?.hasDescription) return view.headline.name;
  return text(decision?.decision_id) || "Decision";
}
