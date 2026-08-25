import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Enterprise Integration | Cortex',
  description: 'How the Cortex platform integrates with enterprise environments, designed to complement existing systems while maintaining strict security boundaries.',
};

export default function EnterprisePage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E5E5E5] font-sans selection:bg-[#10B981] selection:text-[#0A0A0A]">
      <div className="max-w-[1440px] mx-auto px-6 py-24 lg:px-12">
        <header className="mb-20 max-w-3xl">
          <h1 className="text-4xl lg:text-5xl font-medium text-white mb-6 tracking-tight">Enterprise Integration</h1>
          <p className="text-xl text-[#999999] leading-relaxed">
            Designed to integrate with existing operations without disruption. Cortex provides analytical support while strictly adhering to enterprise security controls and data isolation policies.
          </p>
        </header>

        <div className="grid md:grid-cols-2 gap-6 mb-24">
          {/* CFO */}
          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="font-mono text-[#10B981] text-xs tracking-wider mb-2">AUDIENCE: CFO</div>
            <h3 className="text-xl text-white font-medium mb-4">&quot;Does this justify its capital expenditure?&quot;</h3>
            <p className="text-[#999999] text-sm leading-relaxed">
              Cortex is designed to surface inefficiencies and map capital allocation against operational realities. It can be evaluated on its ability to provide high-fidelity financial modeling within the Digital Twin, giving teams a clearer view of cost dynamics before committing to strategic shifts.
            </p>
          </div>

          {/* COO */}
          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="font-mono text-[#10B981] text-xs tracking-wider mb-2">AUDIENCE: COO</div>
            <h3 className="text-xl text-white font-medium mb-4">&quot;How does this impact live operations?&quot;</h3>
            <p className="text-[#999999] text-sm leading-relaxed">
              It is designed to run in parallel to live operations. By utilizing the simulation plane, operational changes can be evaluated for downstream impact. Cortex only transitions to active orchestration when explicitly authorized by defined operational policy and human gatekeepers.
            </p>
          </div>

          {/* Supply Chain */}
          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="font-mono text-[#10B981] text-xs tracking-wider mb-2">AUDIENCE: VP SUPPLY CHAIN</div>
            <h3 className="text-xl text-white font-medium mb-4">&quot;Can it handle our vendor complexity?&quot;</h3>
            <p className="text-[#999999] text-sm leading-relaxed">
              The Graph Intelligence module is built to map multi-tier vendor dependencies. It can be used to identify critical-path vulnerabilities and simulate shock events, allowing teams to prepare contingency strategies based on structural analysis rather than guesswork.
            </p>
          </div>

          {/* CIO/CTO */}
          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="font-mono text-[#10B981] text-xs tracking-wider mb-2">AUDIENCE: CIO / CTO</div>
            <h3 className="text-xl text-white font-medium mb-4">&quot;What is the security boundary?&quot;</h3>
            <p className="text-[#999999] text-sm leading-relaxed">
              Cortex relies on bounded APIs and precise access controls. It does not demand root access or bypass existing IAM. It is designed to consume read-only telemetry by default, requiring specific, scoped keys to execute authorized mutations.
            </p>
          </div>
        </div>

        <div className="mb-24">
          <h2 className="text-3xl text-white font-medium mb-8">Architecture Intent</h2>
          <div className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <div className="grid md:grid-cols-3 gap-8">
              <div className="p-6 bg-[#141414] border border-[#262626]">
                <h4 className="text-white font-mono text-sm tracking-wide mb-3">01. INGESTION</h4>
                <p className="text-[#999999] text-xs leading-relaxed">
                  Telemetry, ERP data, and sensor feeds are ingested via standardized connectors. The data remains isolated and is solely used to update the state model.
                </p>
              </div>
              <div className="p-6 bg-[#1A1A1A] border border-[#10B981]">
                <h4 className="text-[#10B981] font-mono text-sm tracking-wide mb-3">02. CORTEX PLANES</h4>
                <p className="text-[#E5E5E5] text-xs leading-relaxed">
                  Reasoning, simulation, and deliberation occur here. Cortex acts as a computation layer, isolated from the systems of record, generating strategy candidates.
                </p>
              </div>
              <div className="p-6 bg-[#141414] border border-[#262626]">
                <h4 className="text-white font-mono text-sm tracking-wide mb-3">03. ORCHESTRATION</h4>
                <p className="text-[#999999] text-xs leading-relaxed">
                  Only after explicit human authorization, controlled payloads are sent back to enterprise execution systems via scoped APIs.
                </p>
              </div>
            </div>
            <div className="mt-8 text-center text-xs font-mono text-[#666666] tracking-wider uppercase">
              Figure 1: Cortex works alongside existing systems
            </div>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-12">
          <div>
            <h3 className="text-xl text-white font-medium mb-4">Controls & Data Isolation</h3>
            <p className="text-[#999999] text-sm leading-relaxed mb-6">
              Data sovereignty is a core requirement. Models are explicitly designed not to leak proprietary state information across tenant boundaries. Ingestion pipelines apply masking and redaction prior to processing.
            </p>
            <ul className="space-y-3 text-sm text-[#999999]">
              <li className="flex items-start">
                <span className="text-[#10B981] mr-3">■</span>
                Role-Based Access Control (RBAC) integration
              </li>
              <li className="flex items-start">
                <span className="text-[#10B981] mr-3">■</span>
                Ephemeral state processing options
              </li>
              <li className="flex items-start">
                <span className="text-[#10B981] mr-3">■</span>
                Comprehensive audit logs in Decision Memory
              </li>
            </ul>
          </div>
          <div>
            <h3 className="text-xl text-white font-medium mb-4">Staged Adoption Path</h3>
            <p className="text-[#999999] text-sm leading-relaxed mb-6">
              Integration is phased to establish trust and validate models before enabling execution capabilities.
            </p>
            <ul className="space-y-4">
              <li className="border-l-2 border-[#262626] pl-4">
                <div className="text-white text-sm font-medium mb-1">Phase 1: Shadow Mode</div>
                <div className="text-xs text-[#666666]">Read-only ingestion. Evaluates recommendations against historical outcomes.</div>
              </li>
              <li className="border-l-2 border-[#10B981] pl-4">
                <div className="text-white text-sm font-medium mb-1">Phase 2: Human-in-the-loop</div>
                <div className="text-xs text-[#666666]">Surfaces insights for manual review and explicitly authorized execution.</div>
              </li>
              <li className="border-l-2 border-[#262626] pl-4">
                <div className="text-white text-sm font-medium mb-1">Phase 3: Bounded Automation</div>
                <div className="text-xs text-[#666666]">Automated execution strictly within predefined risk and policy bounds.</div>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
