/**
 * Approvals screen — the governed decision (Day 25 §12).
 *
 * The phone only submits APPROVE or REJECT. It does not decide whether the
 * action is valid — the backend validates and drives the governed execution.
 */

import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { listPendingApprovals, decideApproval } from "../api/tasks";
import type { BootstrapApproval } from "../api/bootstrap";

interface Props {
  workspaceId: string;
  onResolved: (taskId: string, approved: boolean, status: string) => void;
}

export function Approvals({ workspaceId, onResolved }: Props) {
  const [approvals, setApprovals] = useState<BootstrapApproval[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setApprovals(await listPendingApprovals());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const decide = useCallback(
    async (approval: BootstrapApproval, approved: boolean) => {
      setBusy(approval.approval_id);
      try {
        const result = await decideApproval(
          approval.task_id,
          workspaceId,
          approved,
          "decided on the phone",
        );
        onResolved(result.task_id, result.approved, result.status);
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(null);
      }
    },
    [workspaceId, onResolved, reload],
  );

  if (loading && approvals.length === 0) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>APPROVALS</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {approvals.length === 0 ? (
        <Text style={styles.muted}>No approvals pending</Text>
      ) : (
        approvals.map((approval) => (
          <View key={approval.approval_id} style={styles.card}>
            <Text style={styles.cardTitle}>APPROVAL REQUIRED</Text>
            <Text style={styles.cardBody}>{`Task: ${approval.task_id}`}</Text>
            <Text style={styles.cardBody}>{`Reason: ${approval.reason ?? "-"}`}</Text>
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={[styles.button, styles.reject]}
                disabled={busy === approval.approval_id}
                onPress={() => void decide(approval, false)}
              >
                <Text style={styles.buttonText}>REJECT</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.button, styles.approve]}
                disabled={busy === approval.approval_id}
                onPress={() => void decide(approval, true)}
              >
                <Text style={styles.buttonText}>APPROVE</Text>
              </TouchableOpacity>
            </View>
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0f14" },
  content: { padding: 24, paddingTop: 64 },
  center: { flex: 1, backgroundColor: "#0b0f14", justifyContent: "center" },
  title: { color: "#f5f7fa", fontSize: 22, fontWeight: "700", letterSpacing: 3, marginBottom: 16 },
  card: { backgroundColor: "#131a22", borderRadius: 12, padding: 16, marginBottom: 16 },
  cardTitle: { color: "#fbbf24", fontSize: 13, fontWeight: "700", letterSpacing: 2, marginBottom: 8 },
  cardBody: { color: "#e2e8f0", fontSize: 14, marginBottom: 4 },
  buttonRow: { flexDirection: "row", gap: 12, marginTop: 16 },
  button: { flex: 1, borderRadius: 8, paddingVertical: 12, alignItems: "center" },
  reject: { backgroundColor: "#7f1d1d" },
  approve: { backgroundColor: "#166534" },
  buttonText: { color: "#ffffff", fontWeight: "700", letterSpacing: 1 },
  error: { color: "#f87171", fontSize: 13, marginBottom: 8 },
  muted: { color: "#5c6975", fontSize: 14 },
});
