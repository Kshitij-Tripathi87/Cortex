"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/Badge";
import { useWorkspace } from "@/lib/useWorkspace";
import { api } from "@/lib/api";

interface Rec {
  rank: number;
  candidate: { name: string; recommendation_type: string; category: string; description: string };
  scores: {
    overall_score: number;
    risk_reduction_score: number;
    cost_score: number;
    time_score: number;
    reversibility_score: number;
    confidence_score: number;
    policy_fit_score: number;
    impact_reduction_score: number;
  };
  explanation: {
    what: string;
    why: string;
    assumptions: string[];
    uncertainties: string[];
    review_guidance: string;
  };
  policy_classification: string;
  reversibility: string;
}

const SCENARIO_TYPES = [
  "supplier_failure",
  "warehouse_outage",
  "route_closure",
  "shipment_delay",
  "demand_spike",
  "demand_drop",
  "inventory_shortage",
  "capacity_constraint",
  "custom",
];

const POLICY_COLORS: Record<string, "default" | "success" | "warning" | "error" | "neutral"> = {
  auto_approved: "success",
  review_required: "warning",
  high_risk: "error",
  policy_restricted: "error",
};

export default function RecommendationsPage() {
  const [workspaceId] = useWorkspace();
  const [scenarioName, setScenarioName] = useState("");
  const [scenarioType, setScenarioType] = useState("supplier_failure");
  const [scenarioDescription, setScenarioDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<{ recommendations: Rec[] } | null>(null);
  const [error, setError] = useState<unknown>(null);

  const generate = async () => {
    if (!scenarioName) return;
    setGenerating(true);
    setError(null);
    try {
      const payload = {
        workspace_id: workspaceId,
        scenario_definition: {
          scenario_id: `scenario-${Date.now()}`,
          workspace_id: workspaceId,
          scenario_type: scenarioType,
          name: scenarioName,
          description: scenarioDescription,
          parameters: [],
        },
        include_explanations: true,
        include_trade_offs: true,
      };
      const data = await api.post<{ snapshot: { recommendations: Rec[] } }>(
        `/api/v1/graph/recommendations/generate?workspace_id=${encodeURIComponent(workspaceId)}`,
        payload,
      );
      setResult(data.snapshot);
    } catch (e) {
      setError(e);
    } finally {
      setGenerating(false);
    }
  };

  const getScoreColor = (s: number) => (s > 0.8 ? "bg-green-500" : s > 0.5 ? "bg-yellow-500" : "bg-red-500");
  const getPolicyColor = (p: string) => POLICY_COLORS[p] || "neutral";

  return (
    <div>
      <PageHeader title="Recommendations" description="Generate and review ranked recommendations from a scenario" />
      <div className="mb-6 bg-white rounded-lg shadow p-4 grid grid-cols-1 md:grid-cols-3 gap-4 items-end">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Scenario Name *</label>
          <input
            type="text"
            value={scenarioName}
            onChange={(e) => setScenarioName(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            placeholder="Supplier X outage plan"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
          <select
            value={scenarioType}
            onChange={(e) => setScenarioType(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          >
            {SCENARIO_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase())}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
          <input
            type="text"
            value={scenarioDescription}
            onChange={(e) => setScenarioDescription(e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            placeholder="Optional context"
          />
        </div>
        <div className="md:col-span-3 flex justify-end">
          <button
            onClick={generate}
            disabled={!scenarioName || generating}
            className="px-6 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {generating ? "Generating..." : "Generate"}
          </button>
        </div>
      </div>
      {generating ? (
        <LoadingState message="Generating recommendations..." />
      ) : error ? (
        <ErrorState error={error} onRetry={generate} />
      ) : result?.recommendations ? (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow p-4 text-sm">
            <span className="text-gray-500">Total: </span>
            <span className="font-semibold">{result.recommendations.length}</span> recommendations
          </div>
          {result.recommendations.map((r) => (
            <div key={r.candidate.recommendation_type + "-" + r.rank} className="bg-white rounded-lg shadow p-5">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <Badge variant="default">#{r.rank}</Badge>
                  <h3 className="text-lg font-semibold ml-2 inline">{r.candidate.name}</h3>
                </div>
                <div className="flex gap-2">
                  <Badge>{r.candidate.recommendation_type.replace(/_/g, " ")}</Badge>
                  <Badge variant={getPolicyColor(r.policy_classification)}>
                    {r.policy_classification.replace(/_/g, " ")}
                  </Badge>
                </div>
              </div>
              <p className="text-sm text-gray-600 mb-4">{r.candidate.description}</p>
              <div className="grid grid-cols-2 gap-2 mb-4">
                {Object.entries(r.scores)
                  .filter(([k]) => k.endsWith("_score"))
                  .map(([k, v]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-gray-500">{k.replace("_score", "").replace(/_/g, " ")}</span>
                        <span className="font-mono">{(v as number).toFixed(2)}</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded h-2">
                        <div
                          className={`h-2 rounded ${getScoreColor(v as number)}`}
                          style={{ width: `${(v as number) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
              </div>
              <details className="mb-3">
                <summary className="text-sm font-semibold cursor-pointer">Explanation</summary>
                <div className="mt-2 text-sm text-gray-700 bg-gray-50 p-3 rounded">
                  <div>
                    <span className="font-medium">What:</span> {r.explanation.what}
                  </div>
                  <div className="mt-1">
                    <span className="font-medium">Why:</span> {r.explanation.why}
                  </div>
                  <div className="mt-2">
                    <span className="font-medium">Assumptions:</span> {r.explanation.assumptions.join(", ") || "None"}
                  </div>
                  <div className="mt-1">
                    <span className="font-medium">Uncertainties:</span> {r.explanation.uncertainties.join(", ") || "None"}
                  </div>
                  <div className="mt-2">
                    <span className="font-medium">Review:</span> {r.explanation.review_guidance}
                  </div>
                </div>
              </details>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No recommendations yet"
          description="Define a scenario above and generate to see ranked actions"
          action={<a href="/scenarios" className="text-blue-600 hover:text-blue-800 text-sm">Go to Scenarios</a>}
        />
      )}
    </div>
  );
}
