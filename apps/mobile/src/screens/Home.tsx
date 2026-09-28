/**
 * Home screen — operational, bootstrap-driven (Day 25 §10).
 *
 * Every field comes from the authoritative snapshot; the phone never
 * treats a local UI state as authoritative. Server state wins.
 */

import React from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, TouchableOpacity, View } from "react-native";
import type { MobileSessionState } from "../state/session";
import type { BootstrapTask } from "../api/bootstrap";

interface Props {
  state: MobileSessionState;
  loading: boolean;
  onTalk: () => void;
  onOpenApprovals: () => void;
  onOpenTask: (task: BootstrapTask) => void;
}

export function Home({ state, loading, onTalk, onOpenApprovals, onOpenTask }: Props) {
  const snapshot = state.snapshot;

  if (loading && !snapshot) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
        <Text style={styles.muted}>Reconstructing state...</Text>
      </View>
    );
  }

  if (!snapshot) {
    return (
      <View style={styles.center}>
        <Text style={styles.title}>VANESSA</Text>
        <Text style={styles.muted}>Not connected. Please sign in.</Text>
      </View>
    );
  }

  const status = state.connection === "CONNECTED" ? "Ready" : state.connection;
  const attention = snapshot.pending_approvals.length;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>VANESSA</Text>
      <Text style={styles.status}>{`\u25CF ${status}`}</Text>

      <Text style={styles.section}>ACTIVE</Text>
      {snapshot.active_tasks.length === 0 ? (
        <Text style={styles.muted}>No active tasks</Text>
      ) : (
        snapshot.active_tasks.map((task) => (
          <TouchableOpacity key={task.task_id} onPress={() => onOpenTask(task)}>
            <View style={styles.row}>
              <Text style={styles.rowTitle}>{task.objective.slice(0, 40)}</Text>
              <Text style={styles.rowValue}>{task.status}</Text>
            </View>
          </TouchableOpacity>
        ))
      )}

      <Text style={styles.section}>DEVICES</Text>
      {snapshot.devices.map((device) => (
        <View key={device.device_id} style={styles.row}>
          <Text style={styles.rowTitle}>
            {`\u25CF ${device.device_id}`}
          </Text>
          <Text style={styles.rowValue}>{device.status}</Text>
        </View>
      ))}

      <Text style={styles.section}>ATTENTION</Text>
      {attention > 0 ? (
        <TouchableOpacity onPress={onOpenApprovals}>
          <Text style={styles.attention}>{`${attention} approval${attention > 1 ? "s" : ""} required`}</Text>
        </TouchableOpacity>
      ) : (
        <Text style={styles.muted}>Nothing needs you</Text>
      )}

      <TouchableOpacity style={styles.talkButton} onPress={onTalk}>
        <Text style={styles.talkText}>TALK</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0f14" },
  content: { padding: 24, paddingTop: 64 },
  center: { flex: 1, backgroundColor: "#0b0f14", alignItems: "center", justifyContent: "center" },
  title: { color: "#f5f7fa", fontSize: 28, fontWeight: "700", letterSpacing: 4 },
  status: { color: "#4ade80", fontSize: 14, marginTop: 8 },
  section: { color: "#8b98a5", fontSize: 12, fontWeight: "700", letterSpacing: 2, marginTop: 28 },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 8,
    borderBottomColor: "#1c2430",
    borderBottomWidth: 1,
  },
  rowTitle: { color: "#e2e8f0", fontSize: 15, flex: 1 },
  rowValue: { color: "#8b98a5", fontSize: 13 },
  attention: { color: "#fbbf24", fontSize: 15, fontWeight: "600" },
  muted: { color: "#5c6975", fontSize: 14, paddingVertical: 6 },
  talkButton: {
    marginTop: 40,
    backgroundColor: "#2563eb",
    borderRadius: 32,
    paddingVertical: 16,
    alignItems: "center",
  },
  talkText: { color: "#ffffff", fontSize: 16, fontWeight: "700", letterSpacing: 2 },
});
