/**
 * Task detail — the operational timeline (Day 25 §11).
 *
 * No hidden chain-of-thought: only operational evidence from the durable
 * records. Tap a node for agent/device/capability/execution/result details.
 */

import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { getTask, type TaskView } from "../api/tasks";

interface Props {
  taskId: string;
}

/** Derive the completed/remaining timeline from the authoritative status. */
function timelineOf(task: TaskView): { label: string; done: boolean; current: boolean }[] {
  const stages = [
    { key: "CREATED", label: "Context reconstructed" },
    { key: "PLANNING", label: "Research complete" },
    { key: "PROPOSED", label: "Code changed" },
    { key: "EXECUTING", label: "Tests passed" },
    { key: "VERIFYING", label: "Verification" },
    { key: "APPROVED", label: "Approval" },
  ];
  const terminalOK = ["COMPLETED"];
  const order = [
    "PENDING",
    "CREATED",
    "PLANNING",
    "PROPOSED",
    "AWAITING_APPROVAL",
    "APPROVED",
    "EXECUTING",
    "VERIFYING",
  ];
  const idx = order.indexOf(task.status);

  return stages.map((stage, i) => {
    const reached = idx >= order.indexOf(stage.key) || terminalOK.includes(task.status);
    return {
      label: stage.label,
      done: reached && !(terminalOK.includes(task.status) && i === stages.length - 1),
      current:
        task.status === stage.key ||
        (terminalOK.includes(task.status) && i === stages.length - 1),
    };
  });
}

export function TaskDetail({ taskId }: Props) {
  const [task, setTask] = useState<TaskView | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTask(await getTask(taskId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>{error}</Text>
      </View>
    );
  }

  if (!task) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>{task.objective.slice(0, 60)}</Text>
      <Text style={styles.status}>{`Status: ${task.status} (v${task.world_state_version})`}</Text>
      {task.blocked_reason ? <Text style={styles.error}>{task.blocked_reason}</Text> : null}
      {task.failure_reason ? <Text style={styles.error}>{task.failure_reason}</Text> : null}

      <Text style={styles.section}>TIMELINE</Text>
      {timelineOf(task).map((node) => (
        <View key={node.label} style={styles.nodeRow}>
          <Text
            style={
              node.done
                ? styles.nodeDone
                : node.current
                  ? styles.nodeCurrent
                  : styles.nodePending
            }
          >
            {`${node.done ? "\u2713" : node.current ? "\u25CF" : "\u25CB"}  ${node.label}`}
          </Text>
        </View>
      ))}

      <Text style={styles.section}>EVIDENCE</Text>
      <Text style={styles.muted}>{`Workspace: ${task.workspace_id}`}</Text>
      <Text style={styles.muted}>{`Created: ${task.created_at}`}</Text>
      <Text style={styles.muted}>{`Requires approval: ${task.requires_approval ? "yes" : "no"}`}</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0f14" },
  content: { padding: 24, paddingTop: 64 },
  center: { flex: 1, backgroundColor: "#0b0f14", justifyContent: "center", padding: 24 },
  title: { color: "#f5f7fa", fontSize: 20, fontWeight: "700" },
  status: { color: "#8b98a5", fontSize: 14, marginTop: 8 },
  section: {
    color: "#8b98a5",
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 2,
    marginTop: 24,
    marginBottom: 8,
  },
  nodeRow: { paddingVertical: 6 },
  nodeDone: { color: "#4ade80", fontSize: 15 },
  nodeCurrent: { color: "#fbbf24", fontSize: 15, fontWeight: "700" },
  nodePending: { color: "#5c6975", fontSize: 15 },
  muted: { color: "#5c6975", fontSize: 13, paddingVertical: 2 },
  error: { color: "#f87171", fontSize: 13 },
});
