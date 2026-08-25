"use client";

import { FormEvent, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { createSupplierFailureBrief, type DecisionBrief } from "@/features/morning-brief/api/client";
import { CriticalAlertCard } from "@/features/morning-brief/components/CriticalAlertCard";
import { ImpactCard } from "@/features/morning-brief/components/ImpactCard";
import { Timeline } from "@/features/morning-brief/components/Timeline";
import { RecommendationPanel } from "@/features/morning-brief/components/RecommendationPanel";
import { EvidenceDrawer } from "@/features/morning-brief/components/EvidenceDrawer";
import { TrustPanel } from "@/features/morning-brief/components/TrustPanel";
import { RoleSwitcher } from "@/features/morning-brief/components/RoleSwitcher";
import { getRole, type Role } from "@/features/morning-brief/roles";

type Section = "critical" | "financial" | "operational" | "timeline" | "recommendations" | "evidence" | "trust";

export default function MorningBriefPage() {
  const [workspaceId, setWorkspaceId] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [brief, setBrief] = useState<DecisionBrief | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState<Role>("cfo");
  const roleConfig = useMemo(() => getRole(role), [role]);

  async function run(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setBrief(
        await createSupplierFailureBrief({
          workspace_id: workspaceId,
          supplier_id: supplierId,
          severity: "critical",
        }),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Unable to compute the Decision Brief.");
    } finally {
      setLoading(false);
    }
  }

  const sections = useMemo(() => {
    if (!brief) return [] as Section[];
    return roleConfig.ordering;
  }, [brief, roleConfig]);

  return (
    <main className="mx-auto max-w-7xl p-6 sm:p-8">
      <header className="mb-6">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
          Cortex / Morning Brief
       </p>
        <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Supplier Disruption Decision Brief</h1>
            <p className="mt-1 text-sm text-slate-600">
              {roleConfig.subtitle}. One screen, one decision, deterministic math.
           </p>
         </div>
          <RoleSwitcher current={role} onChange={setRole} />
       </div>
     </header>

      <form
        onSubmit={run}
        className="mb-6 grid gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm md:grid-cols-[1fr_1fr_auto]"
      >
        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">
            Workspace UUID
         </span>
          <input
            required
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            placeholder="e.g. 55555555-5555-5555-5555-555555555555"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
       </label>
        <label className="block">
          <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-slate-500">
            Supplier UUID
         </span>
          <input
            required
            value={supplierId}
            onChange={(e) => setSupplierId(e.target.value)}
            placeholder="e.g. aaaaaaa1-0000-0000-0000-000000000001"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
          />
       </label>
        <button
          type="submit"
          disabled={loading}
          className="self-end rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-indigo-700 disabled:opacity-60"
        >
          {loading ? "Computing..." : "Supplier fails"}
       </button>
     </form>

      {error && (
        <div className="mb-6 rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      )}

      {brief && (
        <div className="space-y-6">
          {sections.map((section) => {
            switch (section) {
              case "critical":
                return <CriticalAlertCard key={section} brief={brief} />;
              case "financial":
                return <ImpactCard key={section} brief={brief} />;
              case "operational":
                return <ImpactCard key={section} brief={brief} />;
              case "timeline":
                return <Timeline key={section} brief={brief} />;
              case "recommendations":
                return <RecommendationPanel key={section} brief={brief} />;
              case "evidence":
                return <EvidenceDrawer key={section} brief={brief} />;
              case "trust":
                return <TrustPanel key={section} brief={brief} />;
              default:
                return null;
            }
          })}
       </div>
      )}

      {!brief && !error && !loading && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-12 text-center">
          <p className="text-sm font-semibold text-slate-700">No brief yet</p>
          <p className="mt-1 text-xs text-slate-500">
            Enter a workspace UUID and a supplier UUID, then click <b>Supplier fails</b> to compute the brief.
         </p>
       </div>
      )}
   </main>
  );
}
