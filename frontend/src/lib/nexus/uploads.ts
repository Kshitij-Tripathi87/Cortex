/**
 * The list of uploads of a workspace (GET /sources/batches) in words.
 *
 * Each upload moves through: uploaded -> prepared -> reviewed -> published.
 * The server reports where it stands; these functions say it plainly and
 * name the next step. Pure, so the wording is unit-tested.
 */

export interface UploadBatch {
  batch_id: string;
  files: Array<{ name: string; rows: number | null }>;
  uploaded_at: string | null;
  /** published | ready_to_publish | review_required | blocked | nothing_accepted | not_prepared */
  state: string;
  published_version: number | null;
  claims_accepted: number;
  claims_pending_review: number;
  claims_rejected: number;
  open_conflicts: number;
  blocking_conflicts: number;
}

export interface UploadList {
  /** Every upload of the workspace; `batches` holds the most recent ones. */
  batch_count: number;
  batches: UploadBatch[];
}

export type UploadTone = "done" | "todo" | "blocked" | "idle";

export interface UploadStatus {
  label: string;
  tone: UploadTone;
  /** What the state means for this upload, with its own numbers. */
  detail: string;
  /** Text of the link that opens the upload. */
  action: string;
}

function count(value: number, singular: string, plural = `${singular}s`): string {
  return `${value.toLocaleString("en-US")} ${value === 1 ? singular : plural}`;
}

/** "suppliers.csv", "a.csv and b.csv", or a placeholder when the upload has no file row. */
export function uploadName(batch: UploadBatch): string {
  const names = batch.files.map((file) => file.name).filter((name) => name !== "");
  if (names.length === 0) return "Upload without a file name";
  if (names.length === 1) return names[0];
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** "6 rows", or null when the file was not counted. */
export function uploadRows(batch: UploadBatch): string | null {
  const counted = batch.files.filter((file) => typeof file.rows === "number");
  if (counted.length === 0) return null;
  return count(counted.reduce((total, file) => total + (file.rows ?? 0), 0), "row");
}

export function uploadStatus(batch: UploadBatch): UploadStatus {
  switch (batch.state) {
    case "published":
      return {
        label:
          batch.published_version !== null ? `Published · version ${batch.published_version}` : "Published",
        tone: "done",
        detail: `${count(batch.claims_accepted, "value")} accepted and part of your data.`,
        action: "Open",
      };
    case "ready_to_publish":
      return {
        label: "Ready to publish",
        tone: "todo",
        detail: `Every value is reviewed (${count(batch.claims_accepted, "value")} accepted). It is not part of your data until you publish it.`,
        action: "Open and publish",
      };
    case "review_required": {
      const waiting = [];
      if (batch.claims_pending_review > 0) {
        waiting.push(
          `${count(batch.claims_pending_review, "value")} ${batch.claims_pending_review === 1 ? "waits" : "wait"} for a decision`,
        );
      }
      if (batch.open_conflicts > 0) {
        waiting.push(`${count(batch.open_conflicts, "conflict")} ${batch.open_conflicts === 1 ? "is" : "are"} open`);
      }
      return {
        label: "Waiting for review",
        tone: "todo",
        detail: `${waiting.length > 0 ? waiting.join(" and ") : "Some values still need a decision"}. Not part of your data yet.`,
        action: "Review",
      };
    }
    case "blocked":
      return {
        label: "Blocked",
        tone: "blocked",
        detail: `${count(batch.blocking_conflicts, "conflict")} must be resolved before this can be published.`,
        action: "Resolve",
      };
    case "nothing_accepted":
      return {
        label: "Nothing accepted",
        tone: "idle",
        detail: "Every value was rejected, so there is nothing to publish.",
        action: "Open",
      };
    case "not_prepared":
      return {
        label: "Not prepared",
        tone: "idle",
        detail: "The file is stored but its values have not been read yet. Open it and choose Prepare claims.",
        action: "Open and prepare",
      };
    default:
      // A state this site does not know: show it as written rather than guess.
      return { label: batch.state.replaceAll("_", " "), tone: "idle", detail: "", action: "Open" };
  }
}

/** "3 uploads · 1 waits for you" above the list. */
export function uploadListSummary(list: UploadList): string {
  if (list.batch_count === 0) return "No uploads yet";
  const open = list.batches.filter((batch) => batch.state !== "published").length;
  const parts = [count(list.batch_count, "upload")];
  if (open > 0) parts.push(`${open.toLocaleString("en-US")} not published`);
  else if (list.batches.length === list.batch_count) parts.push("all published");
  if (list.batches.length < list.batch_count) {
    parts.push(`showing the ${list.batches.length.toLocaleString("en-US")} most recent`);
  }
  return parts.join(" · ");
}
