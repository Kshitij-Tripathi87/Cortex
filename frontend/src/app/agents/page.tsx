"use client";

import React, { useState } from "react";
import Link from "next/link";

interface Replica {
  replica_id: string;
  agent_id: string;
  version: string;
  status: string;
  workspace_id: string;
  traffic_weight: number;
  is_healthy: boolean;
  infra: {
    cpu_utilization_pct: number;
    memory_mb: number;
    message_lag_ms: number;
    error_rate_pct: number;
  };
  behavioral: {
    prediction_drift_score: number;
    calibration_error: number;
    baseline_disagreement_rate: number;
    policy_violation_count: number;
    is_behaviorally_healthy: boolean;
  };
}

interface Artifact {
  artifact_id: string;
  agent_id: string;
  version: string;
  domain: string;
  lifecycle_state: string;
  canary_traffic_pct: number;
  policy_id: string;
  dataset_version: string;
}

export default function AgentOperationsPage() {
  const [activeTab, setActiveTab] = useState<"fleet" | "training" | "promotion" | "incidents">("fleet");
  const [canaryPct, setCanaryPct] = useState<number>(10);
  const [selectedAgent, setSelectedAgent] = useState<string>("shipment_tracking_agent");
  const [trainingStatus, setTrainingStatus] = useState<string | null>(null);

  const mockArtifacts: Artifact[] = [
    {
      artifact_id: "art_ship_v8",
      agent_id: "shipment_tracking_agent",
      version: "v8",
      domain: "shipment_tracking",
      lifecycle_state: "CANARY",
      canary_traffic_pct: 10,
      policy_id: "nexus-policy-21",
      dataset_version: "ds_logistics_2026_08",
    },
    {
      artifact_id: "art_ship_v7",
      agent_id: "shipment_tracking_agent",
      version: "v7",
      domain: "shipment_tracking",
      lifecycle_state: "ACTIVE",
      canary_traffic_pct: 90,
      policy_id: "nexus-policy-20",
      dataset_version: "ds_logistics_2026_07",
    },
    {
      artifact_id: "art_logistics_v4",
      agent_id: "logistics_routing_agent",
      version: "v4",
      domain: "logistics_routing",
      lifecycle_state: "ACTIVE",
      canary_traffic_pct: 100,
      policy_id: "nexus-policy-19",
      dataset_version: "ds_routes_2026",
    },
  ];

  const mockReplicas: Replica[] = [
    {
      replica_id: "rep-ship-v8-01",
      agent_id: "shipment_tracking_agent",
      version: "v8",
      status: "HEALTHY",
      workspace_id: "ws_austin",
      traffic_weight: 0.1,
      is_healthy: true,
      infra: { cpu_utilization_pct: 14.2, memory_mb: 245.0, message_lag_ms: 3.8, error_rate_pct: 0.0 },
      behavioral: { prediction_drift_score: 0.04, calibration_error: 0.02, baseline_disagreement_rate: 0.05, policy_violation_count: 0, is_behaviorally_healthy: true },
    },
    {
      replica_id: "rep-ship-v7-01",
      agent_id: "shipment_tracking_agent",
      version: "v7",
      status: "HEALTHY",
      workspace_id: "ws_austin",
      traffic_weight: 0.45,
      is_healthy: true,
      infra: { cpu_utilization_pct: 18.5, memory_mb: 230.0, message_lag_ms: 4.1, error_rate_pct: 0.0 },
      behavioral: { prediction_drift_score: 0.06, calibration_error: 0.03, baseline_disagreement_rate: 0.04, policy_violation_count: 0, is_behaviorally_healthy: true },
    },
    {
      replica_id: "rep-ship-v7-02",
      agent_id: "shipment_tracking_agent",
      version: "v7",
      status: "HEALTHY",
      workspace_id: "ws_austin",
      traffic_weight: 0.45,
      is_healthy: true,
      infra: { cpu_utilization_pct: 16.9, memory_mb: 228.0, message_lag_ms: 3.9, error_rate_pct: 0.0 },
      behavioral: { prediction_drift_score: 0.05, calibration_error: 0.02, baseline_disagreement_rate: 0.03, policy_violation_count: 0, is_behaviorally_healthy: true },
    },
    {
      replica_id: "rep-log-v4-01",
      agent_id: "logistics_routing_agent",
      version: "v4",
      status: "HEALTHY",
      workspace_id: "ws_austin",
      traffic_weight: 1.0,
      is_healthy: true,
      infra: { cpu_utilization_pct: 22.1, memory_mb: 310.0, message_lag_ms: 5.2, error_rate_pct: 0.0 },
      behavioral: { prediction_drift_score: 0.02, calibration_error: 0.01, baseline_disagreement_rate: 0.02, policy_violation_count: 0, is_behaviorally_healthy: true },
    },
  ];

  const handleStartTraining = () => {
    setTrainingStatus("Training initiated via Central Training Supervisor across 5 Digital Twin scenarios...");
    setTimeout(() => {
      setTrainingStatus("Training completed. Central Critic joint reward: 4,850. Checkpoint generated: s3://cortex-models/v9.pt");
    }, 2000);
  };

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "#0b0f17", color: "#e2e8f0", fontFamily: "Inter, sans-serif", padding: "2rem" }}>
      {/* Top Header */}
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #1e293b", paddingBottom: "1.5rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
            <Link href="/" style={{ color: "#38bdf8", textDecoration: "none", fontSize: "0.9rem" }}>&larr; Cockpit Home</Link>
            <span style={{ color: "#475569" }}>/</span>
            <span style={{ color: "#94a3b8", fontSize: "0.9rem" }}>Decentralized Fleet</span>
          </div>
          <h1 style={{ fontSize: "1.85rem", fontWeight: 700, marginTop: "0.5rem", letterSpacing: "-0.02em" }}>
            Agent Operations Center
          </h1>
          <p style={{ color: "#94a3b8", fontSize: "0.95rem", margin: "0.25rem 0 0" }}>
            Centralized Training + Decentralized Execution (CTDE) & Progressive Canary Governance
          </p>
        </div>

        <div style={{ display: "flex", gap: "1rem" }}>
          <button
            onClick={handleStartTraining}
            style={{
              backgroundColor: "#2563eb",
              color: "#fff",
              border: "none",
              padding: "0.6rem 1.25rem",
              borderRadius: "6px",
              fontWeight: 600,
              cursor: "pointer",
              fontSize: "0.9rem",
            }}
          >
            + Start Central Training Run
          </button>
        </div>
      </header>

      {/* Metric Highlights */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1.25rem", margin: "2rem 0" }}>
        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", fontWeight: 500 }}>Active Replicas</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.25rem", color: "#38bdf8" }}>{mockReplicas.length} instances</div>
          <div style={{ fontSize: "0.8rem", color: "#10b981", marginTop: "0.25rem" }}>100% healthy & verified</div>
        </div>

        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", fontWeight: 500 }}>Canary Candidate</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.25rem", color: "#f59e0b" }}>v8 (10% Traffic)</div>
          <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.25rem" }}>Baseline v7 (90% Traffic)</div>
        </div>

        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", fontWeight: 500 }}>Avg Prediction Drift</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.25rem", color: "#10b981" }}>0.04 (Nominal)</div>
          <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.25rem" }}>ECE &lt; 0.03 across fleet</div>
        </div>

        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.25rem" }}>
          <div style={{ color: "#94a3b8", fontSize: "0.85rem", fontWeight: 500 }}>Autonomous Replacements</div>
          <div style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.25rem", color: "#a855f7" }}>Zero Incidents</div>
          <div style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.25rem" }}>Self-healing supervisor active</div>
        </div>
      </div>

      {trainingStatus && (
        <div style={{ backgroundColor: "#1e1b4b", border: "1px solid #4338ca", borderRadius: "6px", padding: "1rem", marginBottom: "1.5rem", color: "#c7d2fe" }}>
          ℹ️ {trainingStatus}
        </div>
      )}

      {/* Navigation Tabs */}
      <div style={{ display: "flex", gap: "1rem", borderBottom: "1px solid #1e293b", marginBottom: "1.5rem" }}>
        {(["fleet", "training", "promotion", "incidents"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === tab ? "2px solid #38bdf8" : "2px solid transparent",
              color: activeTab === tab ? "#38bdf8" : "#94a3b8",
              padding: "0.75rem 1rem",
              fontWeight: 600,
              cursor: "pointer",
              textTransform: "capitalize",
            }}
          >
            {tab === "fleet" ? "Active Replicas & Canary" : tab === "training" ? "Central Training Runs" : tab === "promotion" ? "Promotion Gate (10-Phase)" : "Autonomous Incidents"}
          </button>
        ))}
      </div>

      {/* Tab 1: Fleet & Canary */}
      {activeTab === "fleet" && (
        <div>
          {/* Progressive Canary Control */}
          <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem", marginBottom: "2rem" }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>Progressive Canary Traffic Controller</h3>
            <div style={{ display: "flex", alignItems: "center", gap: "2rem" }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.5rem", fontSize: "0.9rem" }}>
                  <span>Baseline v7 ({100 - canaryPct}%)</span>
                  <span style={{ color: "#f59e0b", fontWeight: 600 }}>Candidate v8 ({canaryPct}%)</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={canaryPct}
                  onChange={(e) => setCanaryPct(Number(e.target.value))}
                  style={{ width: "100%", accentColor: "#f59e0b" }}
                />
              </div>

              <button
                onClick={() => alert(`Canary traffic split updated: ${canaryPct}% routed to candidate v8.`)}
                style={{ backgroundColor: "#0284c7", color: "#fff", border: "none", padding: "0.5rem 1.25rem", borderRadius: "6px", fontWeight: 600, cursor: "pointer" }}
              >
                Apply Split
              </button>
            </div>
          </div>

          {/* Replicas Table */}
          <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.9rem" }}>
              <thead>
                <tr style={{ backgroundColor: "#1e293b", color: "#94a3b8" }}>
                  <th style={{ padding: "0.85rem 1rem" }}>Replica ID</th>
                  <th style={{ padding: "0.85rem 1rem" }}>Agent & Version</th>
                  <th style={{ padding: "0.85rem 1rem" }}>Workspace</th>
                  <th style={{ padding: "0.85rem 1rem" }}>Traffic Weight</th>
                  <th style={{ padding: "0.85rem 1rem" }}>CPU / Memory</th>
                  <th style={{ padding: "0.85rem 1rem" }}>Prediction Drift</th>
                  <th style={{ padding: "0.85rem 1rem" }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {mockReplicas.map((r) => (
                  <tr key={r.replica_id} style={{ borderBottom: "1px solid #1e293b" }}>
                    <td style={{ padding: "0.85rem 1rem", fontFamily: "monospace", color: "#38bdf8" }}>{r.replica_id}</td>
                    <td style={{ padding: "0.85rem 1rem" }}>
                      <div style={{ fontWeight: 600 }}>{r.agent_id}</div>
                      <span style={{ fontSize: "0.75rem", backgroundColor: "#334155", padding: "0.15rem 0.4rem", borderRadius: "4px" }}>{r.version}</span>
                    </td>
                    <td style={{ padding: "0.85rem 1rem", color: "#94a3b8" }}>{r.workspace_id}</td>
                    <td style={{ padding: "0.85rem 1rem" }}>{(r.traffic_weight * 100).toFixed(0)}%</td>
                    <td style={{ padding: "0.85rem 1rem", color: "#cbd5e1" }}>{r.infra.cpu_utilization_pct}% / {r.infra.memory_mb} MB</td>
                    <td style={{ padding: "0.85rem 1rem", color: r.behavioral.prediction_drift_score < 0.2 ? "#10b981" : "#f59e0b" }}>
                      {r.behavioral.prediction_drift_score.toFixed(3)}
                    </td>
                    <td style={{ padding: "0.85rem 1rem" }}>
                      <span style={{ backgroundColor: "#065f46", color: "#34d399", padding: "0.2rem 0.5rem", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 600 }}>
                        {r.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 3: Promotion Gate */}
      {activeTab === "promotion" && (
        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem" }}>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>10-Phase Promotion & Qualification Gate</h3>
          <p style={{ color: "#94a3b8", fontSize: "0.9rem", marginBottom: "1.5rem" }}>
            Every agent artifact must pass rigorous unit, behavioral, adversarial, digital twin, and capability manifest verification.
          </p>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            {[
              { name: "1. Deterministic Unit Tests", status: "PASS", score: "100%" },
              { name: "2. Schema Contract Compliance", status: "PASS", score: "Valid" },
              { name: "3. Behavioral Test Suite (Normal, Late, Missing Scans)", status: "PASS", score: "1.00" },
              { name: "4. Safety & Policy Guardrails", status: "PASS", score: "Enforced" },
              { name: "5. Digital Twin Simulation (Multi-hop disruptions)", status: "PASS", score: "0.94" },
              { name: "6. Baseline Outperformance", status: "PASS", score: "+14.8%" },
              { name: "7. Adversarial & Telemetry Noise Robustness", status: "PASS", score: "0.91" },
              { name: "8. Out-of-Distribution (OOD) Resilience", status: "PASS", score: "0.88" },
              { name: "9. Capability Manifest Signature Verification", status: "PASS", score: "Verified (HMAC-SHA256)" },
              { name: "10. Promotion Authorization (Canary Eligible)", status: "PASS", score: "CERTIFIED" },
            ].map((phase, idx) => (
              <div key={idx} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0.85rem", backgroundColor: "#0f172a", borderRadius: "6px", border: "1px solid #1e293b" }}>
                <span style={{ fontSize: "0.9rem", fontWeight: 500 }}>{phase.name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <span style={{ color: "#94a3b8", fontSize: "0.85rem" }}>{phase.score}</span>
                  <span style={{ backgroundColor: "#065f46", color: "#34d399", padding: "0.15rem 0.4rem", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 600 }}>{phase.status}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
