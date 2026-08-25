import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Intelligence Stack | Cortex',
  description: 'Technical details of the Cortex intelligence stack: Graph Intelligence, RL, Multi-Agent Deliberation, and Decision Memory.',
};

export default function IntelligencePage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E5E5E5] font-sans selection:bg-[#10B981] selection:text-[#0A0A0A]">
      <div className="max-w-[1440px] mx-auto px-6 py-24 lg:px-12">
        <header className="mb-20 max-w-3xl">
          <h1 className="text-4xl lg:text-5xl font-medium text-white mb-6 tracking-tight">The Intelligence Stack</h1>
          <p className="text-xl text-[#999999] leading-relaxed">
            A composition of specialized reasoning models designed to evaluate complex system dynamics. Built to operate strictly under policy constraints.
          </p>
        </header>

        <div className="space-y-12 mb-24">
          {/* Section 1 */}
          <section className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <div className="grid lg:grid-cols-12 gap-12">
              <div className="lg:col-span-4">
                <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">01. GRAPH</div>
                <h2 className="text-3xl text-white font-medium mb-4">Graph Intelligence</h2>
                <p className="text-[#999999] text-sm leading-relaxed">
                  Designed to map entities, trace dependencies, and calculate propagation paths across the modeled environment.
                </p>
              </div>
              <div className="lg:col-span-8 grid md:grid-cols-2 gap-8 text-sm">
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">CRITICAL-PATH REASONING</h3>
                  <p className="text-[#999999] leading-relaxed">
                    By projecting state changes across a dependency graph, the system can be evaluated for cascading effects. It identifies bottleneck nodes and secondary impacts before proposals reach the decision plane.
                  </p>
                </div>
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">STRUCTURAL LIMITS</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Analysis is fundamentally bounded by the accuracy of the provided schema and telemetry. We do not make generic claims about GNN architecture performance beyond explicitly tested enterprise topologies.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* Section 2 */}
          <section className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <div className="grid lg:grid-cols-12 gap-12">
              <div className="lg:col-span-4">
                <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">02. RL</div>
                <h2 className="text-3xl text-white font-medium mb-4">Reinforcement Learning</h2>
                <p className="text-[#999999] text-sm leading-relaxed">
                  Utilizes controlled simulation environments for policy evaluation and constraint-aware optimization.
                </p>
              </div>
              <div className="lg:col-span-8 grid md:grid-cols-2 gap-8 text-sm">
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">CONTROLLED EVALUATION</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Candidate actions can be evaluated against reward functions that heavily penalize policy violations. Learning occurs strictly within the offline simulation boundary.
                  </p>
                </div>
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">HUMAN GOVERNANCE</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Optimization objectives are defined by human operators. The RL loop is designed to surface tradeoffs rather than act autonomously, requiring explicit approval for production deployment.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* Section 3 */}
          <section className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <div className="grid lg:grid-cols-12 gap-12">
              <div className="lg:col-span-4">
                <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">03. DELIBERATION</div>
                <h2 className="text-3xl text-white font-medium mb-4">Multi-Agent Synthesis</h2>
                <p className="text-[#999999] text-sm leading-relaxed">
                  Employs specialized agent roles to generate, critique, and refine proposals.
                </p>
              </div>
              <div className="lg:col-span-8 grid md:grid-cols-2 gap-8 text-sm">
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">PERSPECTIVE SYNTHESIS</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Different agents hold distinct constraints (e.g., risk minimal vs. throughput maximal). Deliberation is designed to produce a structured compromise that honors the strictest applied constraint.
                  </p>
                </div>
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">NO POLICY BYPASS</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Internal multi-agent consensus never overrides global policy. The output of the deliberation phase is merely a candidate for the Decision Plane, subject to the same rigorous authorization checks.
                  </p>
                </div>
              </div>
            </div>
          </section>

          {/* Section 4 */}
          <section className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <div className="grid lg:grid-cols-12 gap-12">
              <div className="lg:col-span-4">
                <div className="font-mono text-[#10B981] text-sm tracking-wider mb-4">04. MEMORY</div>
                <h2 className="text-3xl text-white font-medium mb-4">Decision Memory</h2>
                <p className="text-[#999999] text-sm leading-relaxed">
                  The foundational logging structure that preserves the relationship between context, recommendation, and outcome.
                </p>
              </div>
              <div className="lg:col-span-8 grid md:grid-cols-2 gap-8 text-sm">
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">TRACEABILITY</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Every candidate strategy is linked to the state vector that produced it, the policy that authorized it, the human that approved it, and the measured real-world outcome.
                  </p>
                </div>
                <div>
                  <h3 className="text-white font-mono tracking-wide mb-3 border-b border-[#262626] pb-2">FEEDBACK LOOP</h3>
                  <p className="text-[#999999] leading-relaxed">
                    Can be used for retrospective analysis. High-fidelity memory records provide the precise empirical data needed to refine simulation parameters and adjust organizational policies over time.
                  </p>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div className="border-t border-[#262626] pt-12 mt-24 max-w-3xl">
          <h2 className="text-2xl text-white font-medium mb-4">Evaluation Methodology</h2>
          <p className="text-[#999999] mb-8 leading-relaxed">
            We hold our intelligence stack to stringent evaluation standards. We do not rely on generalized LLM benchmarks, but instead validate against specific, controlled enterprise constraints and distribution shifts.
          </p>
          <Link href="/research" className="inline-flex items-center text-[#10B981] font-mono text-sm tracking-wide hover:text-white transition-colors">
            REVIEW RESEARCH METHODOLOGY <span className="ml-2">→</span>
          </Link>
        </div>
      </div>
    </div>
  );
}
