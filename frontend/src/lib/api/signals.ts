import { request } from "./http";
import { OperationalSignal, SignalListResponse } from "@/types/nexus";

interface CanonicalSignalEnvelope {
  data: {
    signals: Array<Record<string, unknown>>;
    count: number;
  };
}

export async function fetchActiveSignals(workspaceId: string): Promise<OperationalSignal[]> {
  const envelope = await request<CanonicalSignalEnvelope>({
    path: "/nexus/signals",
    query: { workspace_id: workspaceId },
  });
  return (envelope.data.signals || []).map((signal) => {
    const affectedEntityIds = Array.isArray(signal.affected_entity_ids)
      ? signal.affected_entity_ids
      : [];
    const affectedEntityTypes = Array.isArray(signal.affected_entity_types)
      ? signal.affected_entity_types
      : [];
    const evidence = signal.feature_evidence;
    const evidenceRecord = evidence && typeof evidence === "object"
      ? evidence as Record<string, unknown>
      : {};
    return {
      signal_id: String(signal.signal_id ?? ""),
      entity_id: String(affectedEntityIds[0] ?? ""),
      entity_type: String(affectedEntityTypes[0] ?? ""),
      signal_type: String(signal.signal_name ?? "operational_signal"),
      severity: String(signal.severity ?? "LOW").toUpperCase() as OperationalSignal["severity"],
      confidence: Number(signal.confidence ?? 0),
      metric_value: Number(evidenceRecord.metric_value ?? 0),
      baseline_threshold: Number(evidenceRecord.baseline_threshold ?? 0),
      deviation_pct: Number(evidenceRecord.deviation_pct ?? 0),
      detected_at: String(signal.created_at ?? ""),
      evidence: [String(signal.explanation ?? "")].filter(Boolean),
    } satisfies OperationalSignal;
  });
}

export async function fetchPrimaryBlastRadius(
  workspaceId: string,
): Promise<Record<string, unknown> | null> {
  await fetchActiveSignals(workspaceId);
  return null;
}
