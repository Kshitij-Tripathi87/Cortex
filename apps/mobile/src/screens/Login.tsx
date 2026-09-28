/**
 * Login screen — the first step of the phone flow (Day 25 §3).
 */

import React, { useState } from "react";
import { StyleSheet, Text, TextInput, TouchableOpacity, View } from "react-native";

interface Props {
  onAuthenticated: () => void;
}

export function Login({ onAuthenticated }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>VANESSA</Text>
      <TextInput
        style={styles.input}
        placeholder="email"
        placeholderTextColor="#5c6975"
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <TextInput
        style={styles.input}
        placeholder="password"
        placeholderTextColor="#5c6975"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <TouchableOpacity
        style={styles.button}
        disabled={busy || !email || !password}
        onPress={onAuthenticated}
      >
        <Text style={styles.buttonText}>{busy ? "Signing in..." : "SIGN IN"}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0b0f14", justifyContent: "center", padding: 24 },
  title: { color: "#f5f7fa", fontSize: 28, fontWeight: "700", letterSpacing: 4, textAlign: "center", marginBottom: 40 },
  input: {
    backgroundColor: "#131a22",
    color: "#e2e8f0",
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 12,
    marginBottom: 12,
  },
  button: { backgroundColor: "#2563eb", borderRadius: 8, paddingVertical: 14, alignItems: "center", marginTop: 8 },
  buttonText: { color: "#ffffff", fontWeight: "700", letterSpacing: 1 },
  error: { color: "#f87171", fontSize: 13, marginBottom: 8 },
});
