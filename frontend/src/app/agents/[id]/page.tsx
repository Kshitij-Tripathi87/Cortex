"use client";

import React, { useState } from "react";
import Link from "next/link";

interface AgentDetailPageProps {
  params: { id: string };
}

export default function AgentDetailPage({ params }: AgentDetailPageProps) {
  const [activeTab, setActiveTab] = useState<
    "overview" | "messages" | "decisions" | "training" | "evaluation" | "versions" | "memory" | "security" | "deployments"
  >("overview");

  const agentId = params.id || "shipment_tracking_agent";

  return (
    <div style={{ minHeight: "100vh", backgroundColor: "#0b0f17", color: "#e2e8f0", fontFamily: "Inter, sans-serif", padding: "2rem" }}>
      {/* Header Breadcrumb */}
      <header style={{ borderBottom: "1px solid #1e293b", paddingBottom: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", fontSize: "0.9rem" }}>
          <Link href="/agents" style={{ color: "#38bdf8", textDecoration: "none" }}>&larr; Agent Fleet</Link>
          <span style={{ color: "#475569" }}>/</span>
          <span style={{ color: "#94a3b8" }}>{agentId}</span>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginTop: "1rem" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <h1 style={{ fontSize: "2rem", fontWeight: 700, margin: 0, letterSpacing: "-0.02em" }}>
                {agentId}
              </h1>
              <span style={{ backgroundColor: "#065f46", color: "#34d399", padding: "0.25rem 0.6rem", borderRadius: "4px", fontSize: "0.8rem", fontWeight: 600 }}>
                ACTIVE (CANARY 10%)
              </span>
            </div>
            <p style={{ color: "#94a3b8", fontSize: "0.95rem", margin: "0.35rem 0 0" }}>
              Domain: <strong style={{ color: "#cbd5e1" }}>Shipment Tracking & Port Exception Detection</strong> | Current Version: <strong style={{ color: "#38bdf8" }}>v8</strong> | Active Replicas: <strong style={{ color: "#f59e0b" }}>4 instances</strong>
            </p>
          </div>

          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button style={{ backgroundColor: "#334155", color: "#fff", border: "none", padding: "0.5rem 1rem", borderRadius: "6px", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem" }}>
              Scale Replicas
            </button>
            <button style={{ backgroundColor: "#991b1b", color: "#fff", border: "none", padding: "0.5rem 1rem", borderRadius: "6px", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem" }}>
              Rollback to v7
            </button>
          </div>
        </div>
      </header>

      {/* 9 Navigation Tabs */}
      <div style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid #1e293b", margin: "1.5rem 0", overflowX: "auto" }}>
        {[
          { id: "overview", label: "Overview" },
          { id: "messages", label: "Messages" },
          { id: "decisions", label: "Decisions" },
          { id: "training", label: "Training" },
          { id: "evaluation", label: "Evaluation (10-Phase)" },
          { id: "versions", label: "Versions" },
          { id: "memory", label: "Memory & State" },
          { id: "security", label: "Security & Manifest" },
          { id: "deployments", label: "Deployments (Replicas)" },
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id as any)}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === t.id ? "2px solid #38bdf8" : "2px solid transparent",
              color: activeTab === t.id ? "#38bdf8" : "#94a3b8",
              padding: "0.75rem 1rem",
              fontWeight: 600,
              fontSize: "0.9rem",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Overview */}
      {activeTab === "overview" && (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "1.5rem" }}>
          <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem" }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>Runtime & Behavioral Telemetry</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem" }}>
              <div style={{ backgroundColor: "#0f172a", padding: "1rem", borderRadius: "6px", border: "1px solid #1e293b" }}>
                <div style={{ color: "#94a3b8", fontSize: "0.8rem" }}>Prediction Drift</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "#10b981", marginTop: "0.25rem" }}>0.04 (Nominal)</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Threshold: &lt; 0.35</div>
              </div>

              <div style={{ backgroundColor: "#0f172a", padding: "1rem", borderRadius: "6px", border: "1px solid #1e293b" }}>
                <div style={{ color: "#94a3b8", fontSize: "0.8rem" }}>Expected Calibration Error</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "#10b981", marginTop: "0.25rem" }}>0.02 (Calibrated)</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>Threshold: &lt; 0.10</div>
              </div>

              <div style={{ backgroundColor: "#0f172a", padding: "1rem", borderRadius: "6px", border: "1px solid #1e293b" }}>
                <div style={{ color: "#94a3b8", fontSize: "0.8rem" }}>P99 Inference Latency</div>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "#38bdf8", marginTop: "0.25rem" }}>38.2 ms</div>
                <div style={{ fontSize: "0.75rem", color: "#64748b" }}>SLA: &lt; 100 ms</div>
              </div>
            </div>

            <h4 style={{ fontSize: "1rem", fontWeight: 600, margin: "1.5rem 0 0.75rem" }}>Current Capabilities & Constraints</h4>
            <ul style={{ color: "#94a3b8", fontSize: "0.9rem", lineHeight: "1.6", margin: 0, paddingLeft: "1.25rem" }}>
              <li><strong>READ:</strong> Access to real-time shipment telemetry, port congestion index, and weather forecasts.</li>
              <li><strong>PROPOSE:</strong> Generates air-freight expedite and port reroute proposals with cost/benefit ROI.</li>
              <li><strong>SIMULATE:</strong> Executes Digital Twin delay projections.</li>
              <li><strong style={{ color: "#f87171" }}>EXECUTE: FORBIDDEN</strong> (Privilege separation enforced — HITL decision card required).</li>
            </ul>
          </div>

          <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem" }}>
            <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>Artifact Provenance</h3>
            <div style={{ fontSize: "0.85rem", color: "#94a3b8", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <div><strong>Artifact ID:</strong> <span style={{ fontFamily: "monospace", color: "#38bdf8" }}>art_ship_v8_01a0</span></div>
              <div><strong>Model Checkpoint:</strong> <span style={{ fontFamily: "monospace", color: "#cbd5e1" }}>s3://cortex-models/v8.pt</span></div>
              <div><strong>Policy ID:</strong> <span style={{ fontFamily: "monospace", color: "#cbd5e1" }}>policy_shipment_v8</span></div>
              <div><strong>Training Dataset:</strong> <span style={{ color: "#cbd5e1" }}>ds_logistics_2026_08</span></div>
              <div><strong>HMAC Signature:</strong> <span style={{ fontFamily: "monospace", color: "#10b981" }}>verified (a4f9...81c2)</span></div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 8: Security & Manifest */}
      {activeTab === "security" && (
        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem" }}>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>Signed Capability Manifest (HMAC-SHA256)</h3>
          <p style={{ color: "#94a3b8", fontSize: "0.9rem", marginBottom: "1.5rem" }}>
            Nexus runtime validates the cryptographic signature of the capability manifest before starting any replica.
          </p>

          <pre style={{ backgroundColor: "#0f172a", padding: "1.25rem", borderRadius: "6px", border: "1px solid #1e293b", color: "#38bdf8", fontFamily: "monospace", fontSize: "0.85rem", overflowX: "auto" }}>
{`{
  "agent_id": "shipment_tracking_agent",
  "version": "v8",
  "allowed_capabilities": ["read", "propose", "simulate"],
  "allowed_tools": ["get_shipment_telemetry", "get_port_congestion", "simulate_eta"],
  "max_tokens_per_turn": 100000,
  "max_cost_per_turn_usd": 5.0,
  "policy_id": "policy_shipment_tracking_agent_v8",
  "signature": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "verification_status": "VALID_AND_SIGNED"
}`}
          </pre>
        </div>
      )}

      {/* Tab 9: Deployments & Replicas */}
      {activeTab === "deployments" && (
        <div style={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px", padding: "1.5rem" }}>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 600, margin: "0 0 1rem" }}>Active Decentralized Replicas (4 instances)</h3>
          <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ backgroundColor: "#1e293b", color: "#94a3b8" }}>
                <th style={{ padding: "0.85rem 1rem" }}>Replica ID</th>
                <th style={{ padding: "0.85rem 1rem" }}>Version</th>
                <th style={{ padding: "0.85rem 1rem" }}>Node</th>
                <th style={{ padding: "0.85rem 1rem" }}>Traffic</th>
                <th style={{ padding: "0.85rem 1rem" }}>CPU / Memory</th>
                <th style={{ padding: "0.85rem 1rem" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {[
                { id: "rep-ship-v8-01", ver: "v8 (Canary)", node: "worker-01", traffic: "10%", cpu: "14.2%", mem: "245 MB", status: "HEALTHY" },
                { id: "rep-ship-v7-01", ver: "v7 (Baseline)", node: "worker-01", traffic: "45%", cpu: "18.5%", mem: "230 MB", status: "HEALTHY" },
                { id: "rep-ship-v7-02", ver: "v7 (Baseline)", node: "worker-02", traffic: "45%", cpu: "16.9%", mem: "228 MB", status: "HEALTHY" },
              ].map((r) => (
                <tr key={r.id} style={{ borderBottom: "1px solid #1e293b" }}>
                  <td style={{ padding: "0.85rem 1rem", fontFamily: "monospace", color: "#38bdf8" }}>{r.id}</td>
                  <td style={{ padding: "0.85rem 1rem" }}>{r.ver}</td>
                  <td style={{ padding: "0.85rem 1rem", color: "#94a3b8" }}>{r.node}</td>
                  <td style={{ padding: "0.85rem 1rem" }}>{r.traffic}</td>
                  <td style={{ padding: "0.85rem 1rem", color: "#cbd5e1" }}>{r.cpu} / {r.mem}</td>
                  <td style={{ padding: "0.85rem 1rem" }}>
                    <span style={{ backgroundColor: "#065f46", color: "#34d399", padding: "0.2rem 0.5rem", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 600 }}>{r.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
