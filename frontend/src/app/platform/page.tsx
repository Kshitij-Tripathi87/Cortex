import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Platform Architecture | Cortex',
  description: 'The six planes of the Cortex platform architecture, designed to provide comprehensive system understanding and controlled decision-making.',
};

export default function PlatformPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E5E5E5] font-sans selection:bg-[#10B981] selection:text-[#0A0A0A]">
      <div className="max-w-[1440px] mx-auto px-6 py-24 lg:px-12">
        <header className="mb-20 max-w-3xl">
          <h1 className="text-4xl lg:text-5xl font-medium text-white mb-6 tracking-tight">The Cortex Platform</h1>
          <p className="text-xl text-[#999999] leading-relaxed">
            The platform is designed around six logical planes. Each plane focuses on a specific aspect of state ingestion, reasoning, evaluation, and structured output.
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-24">
          {/* Plane 1 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_01</div>
            <h2 className="text-2xl text-white font-medium mb-2">World Model</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">State Grounding</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              Designed to ingest external signals, normalize inputs, and build a unified representation of the operating environment. Provides the foundation for higher-level reasoning.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">Telemetry, APIs, Databases</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">Normalized State Vectors</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Scope is strictly limited to defined ingestion pathways.
            </div>
          </div>

          {/* Plane 2 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_02</div>
            <h2 className="text-2xl text-white font-medium mb-2">Digital Twin</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">System Simulation</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              Maintains an executable model of enterprise dynamics. Can be used to run counterfactuals and validate potential state changes in isolation before deployment.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">State Vectors, Constraints</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">Simulation Scenarios</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Simulation fidelity depends on structural completeness.
            </div>
          </div>

          {/* Plane 3 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_03</div>
            <h2 className="text-2xl text-white font-medium mb-2">Intelligence</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">Inference & Search</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              Applies graph analysis, reinforcement learning constraints, and multi-agent deliberation to identify optimal paths within the validated simulation environment.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">Simulation Results, Objectives</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">Strategy Candidates</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Evaluated against predefined safety invariants.
            </div>
          </div>

          {/* Plane 4 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_04</div>
            <h2 className="text-2xl text-white font-medium mb-2">Decision</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">Policy Governance</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              The control threshold. Subjects candidate strategies to rigorous policy checks, risk bounds evaluation, and explicit human authorization workflows.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">Strategy Candidates, Policy</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">Authorized Actions</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Cannot bypass required human approvals.
            </div>
          </div>

          {/* Plane 5 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_05</div>
            <h2 className="text-2xl text-white font-medium mb-2">Execution</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">Controlled Orchestration</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              Translates authorized actions into system-specific commands. Manages integration delivery, retry logic, and fallback procedures.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">Authorized Actions</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">System Mutations</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Operates exclusively within designated API limits.
            </div>
          </div>

          {/* Plane 6 */}
          <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col group">
            <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">PLANE_06</div>
            <h2 className="text-2xl text-white font-medium mb-2">Memory</h2>
            <div className="text-xs font-mono text-[#666666] uppercase tracking-wider mb-6">Outcome Tracking</div>
            <p className="text-[#999999] text-sm leading-relaxed mb-8 flex-grow">
              Records the full lineage: initial state, intelligence recommendation, policy authorization, execution payload, and ultimate real-world outcome.
            </p>
            <div className="space-y-4">
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">CONSUMES:</div>
                <div className="text-sm text-[#E5E5E5]">Execution Logs, State Delta</div>
              </div>
              <div>
                <div className="font-mono text-xs text-[#666666] mb-1">PRODUCES:</div>
                <div className="text-sm text-[#E5E5E5]">Audit Lineage, RL Rewards</div>
              </div>
            </div>
            <div className="mt-8 pt-4 border-t border-[#262626] text-xs text-[#666666]">
              Note: Immutable ledger for retrospective analysis.
            </div>
          </div>
        </div>

        <div className="bg-[#141414] border border-[#262626] p-12 text-center max-w-4xl mx-auto">
          <h2 className="text-2xl text-white font-medium mb-4">Deep Dive into the Architecture</h2>
          <p className="text-[#999999] mb-8 max-w-2xl mx-auto">
            Review the technical specifications, integration requirements, and security boundaries that govern the six planes.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/enterprise" className="px-6 py-3 bg-[#111111] border border-[#262626] text-white font-mono text-sm tracking-wide hover:bg-[#1A1A1A] transition-colors">
              VIEW INTEGRATION
            </Link>
            <Link href="/intelligence" className="px-6 py-3 bg-[#10B981] text-[#0A0A0A] font-mono text-sm tracking-wide hover:bg-[#059669] transition-colors">
              EXPLORE INTELLIGENCE
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
