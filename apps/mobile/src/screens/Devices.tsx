/**
 * Devices screen — the same DeviceMesh state the backend sees (Day 25 §13).
 */

import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import { heartbeat, listDevices } from "../api/devices";
import type { BootstrapDevice } from "../api/bootstrap";

export function Devices() {
  const [devices, setDevices] = useState<BootstrapDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDevices(await listDevices());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>DEVICES</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {loading && devices.length === 0 ? (
        <ActivityIndicator />
      ) : devices.length === 0 ? (
        <Text style={styles.muted}>No devices registered</Text>
      ) : (
        devices.map((device) => (
          <View key={device.device_id} style={styles.card}>
            <Text style={styles.cardTitle}>{`\u25CF ${device.device_id.toUpperCase()}`}</Text>
            <Text style={styles.cardBody}>{`${device.platform} - ${device.status}`}</Text>
            <Text style={styles.cardMuted}>{`${device.capabilities.length} capabilities`}</Text>
            <Text style={styles.cardMuted}>{`Last seen: ${device.last_seen}`}</Text>
            <TouchableOpacity
              style={styles.beatButton}
              onPress={() => void heartbeat(device.device_id).then(load)}
            >
              <Text style={styles.beatText}>HEARTBEAT</Text>
            </TouchableOpacity>
          </View>
        ))
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0f14" },
  content: { padding: 24, paddingTop: 64 },
  title: { color: "#f5f7fa", fontSize: 22, fontWeight: "700", letterSpacing: 3, marginBottom: 16 },
  card: { backgroundColor: "#131a22", borderRadius: 12, padding: 16, marginBottom: 12 },
  cardTitle: { color: "#e2e8f0", fontSize: 14, fontWeight: "700", letterSpacing: 1 },
  cardBody: { color: "#8b98a5", fontSize: 13, marginTop: 6 },
  cardMuted: { color: "#5c6975", fontSize: 12, marginTop: 2 },
  beatButton: {
    alignSelf: "flex-start",
    backgroundColor: "#1e293b",
    borderRadius: 6,
    paddingHorizontal: 12,
    paddingVertical: 6,
    marginTop: 10,
  },
  beatText: { color: "#93c5fd", fontSize: 11, fontWeight: "700", letterSpacing: 1 },
  error: { color: "#f87171", fontSize: 13, marginBottom: 8 },
  muted: { color: "#5c6975", fontSize: 14 },
});
