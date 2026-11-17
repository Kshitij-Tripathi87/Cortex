/**
 * Presentation helpers for the workspace Ask box.
 *
 * Pure functions, so the questions the UI offers and the way it summarises
 * evidence can be unit-tested without rendering a component.
 */

/** A record the user has selected in the cockpit (an open risk). */
export interface AskSelection {
  entity_id: string;
  entity_name?: string | null;
}

/** One evidence record of the `/nexus/vanessa/ask` response. */
export interface AskEvidenceItem {
  tool?: unknown;
  source?: unknown;
  /** One readable line written by the server: what the tool read. */
  summary?: unknown;
  /** Raw tool output, or a shortened JSON string of it. */
  data_excerpt?: unknown;
}

/**
 * Questions offered as one-click suggestions. Each is a complete question the
 * assistant answers from the published data. A question about the selected
 * record names its identifier, because the server only receives the text.
 */
export function askSuggestions(selection?: AskSelection | null): string[] {
  const questions = [
    "What changed?",
    "Which orders are exposed?",
    "Which orders are late?",
    "What is below safety stock?",
  ];
  const entityId = selection?.entity_id?.trim();
  if (entityId) {
    questions.unshift(`What does the data show about ${entityId}?`);
  }
  return questions;
}

/** Input placeholder: an example the assistant can answer as typed. */
export function askPlaceholder(selection?: AskSelection | null): string {
  const entityId = selection?.entity_id?.trim();
  return entityId ? `Why is ${entityId} affected?` : "Ask about the data in this workspace";
}

function shorten(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
}

/**
 * One line describing an evidence record. Uses the server's summary; older
 * responses without one fall back to the first fields of the raw excerpt.
 */
export function evidenceSummary(item: AskEvidenceItem, limit = 220): string {
  if (typeof item.summary === "string" && item.summary.trim()) {
    return shorten(item.summary.trim(), limit);
  }
  const excerpt = item.data_excerpt;
  if (typeof excerpt === "string") {
    return excerpt.trim() ? shorten(excerpt.trim(), limit) : "—";
  }
  if (excerpt && typeof excerpt === "object") {
    const parts = Object.entries(excerpt as Record<string, unknown>)
      .slice(0, 4)
      .map(([key, value]) => {
        if (Array.isArray(value)) return `${key}: ${value.length} item${value.length === 1 ? "" : "s"}`;
        if (value && typeof value === "object") return `${key}: ${Object.keys(value).length} fields`;
        return `${key}: ${String(value)}`;
      });
    return parts.length > 0 ? shorten(parts.join(" · "), limit) : "—";
  }
  return excerpt === undefined || excerpt === null ? "—" : shorten(String(excerpt), limit);
}

/** Label of the tool behind an evidence record. */
export function evidenceTool(item: AskEvidenceItem, index: number): string {
  return typeof item.tool === "string" && item.tool ? item.tool : `evidence_${index + 1}`;
}
