/**
 * What the Command Center shows about the published records.
 *
 * The figures come from GET /nexus/workspace/overview, which the server
 * derives from the records with the code that also answers the Ask box. The
 * functions here only arrange that answer for the page: they add no number
 * of their own, and where nothing was checked they say so instead of
 * showing a zero.
 */

export interface OverviewRef {
  entity_type: string;
  entity_id: string;
  name: string | null;
}

export interface LateItem {
  entity_type: string;
  entity_id: string;
  /** Everyday name of the kind of record: "purchase order". */
  noun: string;
  days_late: number | null;
  status: string | null;
  promised_date: string | null;
  expected_date: string | null;
  /** What it carries: "400 x C-2000 Cast Iron Housing from S-101 Bharat Castings". May be empty. */
  subject: string;
  /** Why it counts as late, from the dates and status of the record itself. */
  reasons: string;
  text: string;
}

export interface StockItem {
  entity_type: string;
  entity_id: string;
  product: OverviewRef | null;
  facility: OverviewRef | null;
  on_hand: number;
  threshold: number | null;
  threshold_field: string | null;
  out_of_stock: boolean;
  /** Which stock: "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store". */
  where: string;
  /** The figures it is judged on: "120 on hand against a safety stock of 300 (180 short)". */
  detail: string;
  text: string;
}

export interface FlaggedItem {
  entity_type: string;
  entity_id: string;
  name: string | null;
  noun: string;
  status: string;
  text: string;
}

export interface WorkspaceOverview {
  /** The day lateness is judged against (UTC), as an ISO date. */
  as_of: string;
  /** Null until a first upload has been published. */
  published: { version: number; published_at: string | null; files: string[] } | null;
  records: { total: number; by_type: Array<{ entity_type: string; noun: string; count: number }> };
  relationships: { total: number };
  reading: { complete: boolean; records_read: number; records_total: number };
  /** The sentences the Ask box gives for "What needs attention?". */
  summary: string[];
  late: { count: number; checked: number; items: LateItem[] };
  stock: { count: number; checked: number; items: StockItem[] };
  flagged: { count: number; items: FlaggedItem[] };
  attention_count: number;
}

export interface Tile {
  label: string;
  value: string;
  detail: string;
}

export interface QueueEntry {
  key: string;
  kind: "late" | "stock" | "flagged";
  badge: string;
  title: string;
  lines: string[];
  /** A complete question for the Ask box about this record. */
  question: string;
}

const NOT_PUBLISHED = "No data published yet";

/** Grouped like the server's sentences ("1,500"), so one page uses one style. */
export function formatCount(value: number): string {
  return value.toLocaleString("en-US");
}

function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function label(ref: { entity_id: string; name: string | null }): string {
  return ref.name && ref.name !== ref.entity_id ? `${ref.entity_id} ${ref.name}` : ref.entity_id;
}

/** "17 Nov 2026" for an ISO date, read as the calendar day it names. */
export function formatIsoDay(isoDate: string): string {
  const date = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return isoDate;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** "17 Nov 2026, 14:05" in the visitor's own time zone. */
export function formatMoment(isoTimestamp: string | null): string | null {
  if (!isoTimestamp) return null;
  const date = new Date(isoTimestamp);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

/** The "Workspace state" card. Totals come from the server, not from a page of a list. */
export function workspaceState(
  overview: WorkspaceOverview | null,
): Array<{ label: string; value: string }> {
  if (!overview) {
    return [
      { label: "Published data", value: "—" },
      { label: "Records", value: "—" },
      { label: "Relationships", value: "—" },
    ];
  }
  const published = overview.published;
  const rows = [
    { label: "Published data", value: published ? `Version ${published.version}` : "Nothing published" },
  ];
  const when = published ? formatMoment(published.published_at) : null;
  if (when) rows.push({ label: "Last published", value: when });
  rows.push(
    { label: "Records", value: formatCount(overview.records.total) },
    { label: "Relationships", value: formatCount(overview.relationships.total) },
  );
  return rows;
}

/**
 * The four figures under the heading. A dash means "nothing to check", which
 * is not the same as zero: a workspace without purchase orders has no late
 * orders, but nobody checked any.
 */
export function cockpitTiles(
  overview: WorkspaceOverview | null,
  risks: ReadonlyArray<{ severity: string }>,
  /** Why there is no overview: it is on its way, or the request failed. */
  missing: "loading" | "failed" = "loading",
): Tile[] {
  const critical = risks.filter((risk) => risk.severity === "CRITICAL").length;
  const high = risks.filter((risk) => risk.severity === "HIGH").length;
  const riskTile: Tile = {
    label: "Recorded risks",
    value: formatCount(risks.length),
    detail:
      risks.length > 0
        ? `${critical} critical · ${high} high`
        : "Risk records come from the API, not from uploads",
  };
  if (!overview) {
    const detail = missing === "failed" ? "Could not be read" : "Reading your data…";
    return [
      { label: "Late orders", value: "—", detail },
      { label: "Stock below threshold", value: "—", detail },
      { label: "Flagged partners", value: "—", detail },
      riskTile,
    ];
  }
  const published = overview.published !== null;
  const { late, stock, flagged } = overview;
  return [
    {
      label: "Late orders",
      value: late.checked > 0 ? formatCount(late.count) : "—",
      detail: !published
        ? NOT_PUBLISHED
        : late.checked > 0
          ? `of ${formatCount(late.checked)} orders and shipments checked`
          : "No orders or shipments in your data",
    },
    {
      label: "Stock below threshold",
      value: stock.checked > 0 ? formatCount(stock.count) : "—",
      detail: !published
        ? NOT_PUBLISHED
        : stock.checked > 0
          ? `of ${formatCount(stock.checked)} stock records checked`
          : "No stock records in your data",
    },
    {
      label: "Flagged partners",
      value: published ? formatCount(flagged.count) : "—",
      detail: published ? "Suppliers, carriers or customers whose own status marks a problem" : NOT_PUBLISHED,
    },
    riskTile,
  ];
}

/** What stands out in the data, most pressing kind first, as rows of the attention queue. */
export function attentionQueue(overview: WorkspaceOverview | null): QueueEntry[] {
  if (!overview) return [];
  const late: QueueEntry[] = overview.late.items.map((item) => ({
    key: `late:${item.entity_type}:${item.entity_id}`,
    kind: "late",
    badge:
      item.days_late !== null && item.days_late > 0
        ? `${formatCount(item.days_late)} day${item.days_late === 1 ? "" : "s"} late`
        : "Flagged",
    title: `${capitalize(item.noun)} ${item.entity_id}`,
    lines: [item.subject, capitalize(item.reasons)].filter((line) => line !== ""),
    question: `Tell me about ${item.entity_id}`,
  }));
  const stock: QueueEntry[] = overview.stock.items.map((item) => ({
    key: `stock:${item.entity_type}:${item.entity_id}`,
    kind: "stock",
    badge: item.out_of_stock ? "Out of stock" : "Low stock",
    title: item.where,
    lines: [capitalize(item.detail)],
    question: `Tell me about ${item.product?.entity_id ?? item.entity_id}`,
  }));
  const flagged: QueueEntry[] = overview.flagged.items.map((item) => ({
    key: `flagged:${item.entity_type}:${item.entity_id}`,
    kind: "flagged",
    badge: "Flagged",
    title: label(item),
    lines: [`${capitalize(item.noun)} with status ${item.status}`],
    question: `Tell me about ${item.entity_id}`,
  }));
  return [...late, ...stock, ...flagged];
}

/** How many findings the list leaves out (the server lists ten of each kind). */
export function unlistedCount(overview: WorkspaceOverview | null): number {
  if (!overview) return 0;
  const listed = overview.late.items.length + overview.stock.items.length + overview.flagged.items.length;
  return Math.max(0, overview.attention_count - listed);
}

/** What the queue says when it has no row. */
export function emptyQueueMessage(
  overview: WorkspaceOverview | null,
  missing: "loading" | "failed" = "loading",
): { title: string; detail: string } {
  if (!overview) {
    return missing === "failed"
      ? { title: "Your data could not be read", detail: "Use Retry at the top of the page." }
      : { title: "Reading your published data…", detail: "" };
  }
  if (overview.published === null) {
    return {
      title: "Nothing to check yet",
      detail:
        "Upload a file, review it and publish it. Cortex then lists late orders, low stock and flagged partners here, read from your own records.",
    };
  }
  return {
    title: "Nothing stands out",
    // The server's own sentences: they also say when a kind of record is
    // missing, so "nothing stands out" is never read as "everything is fine".
    detail: overview.summary.join(" "),
  };
}

/** One line under the figures: which data they were read from, and when. */
export function sourceLine(overview: WorkspaceOverview | null): string | null {
  if (!overview || overview.published === null) return null;
  const parts = [
    `Read from your published data, version ${overview.published.version}`,
    `lateness judged on ${formatIsoDay(overview.as_of)} (UTC)`,
  ];
  if (!overview.reading.complete) {
    parts.push(
      `only ${formatCount(overview.reading.records_read)} of ${formatCount(overview.reading.records_total)} records were read, so the findings cover that part`,
    );
  }
  return `${parts.join(" · ")}.`;
}
