import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Research & Methodology | Cortex',
  description: 'Our principles for evaluating system intelligence. We focus on rigorous methodology over generalized marketing claims.',
};

export default function ResearchPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-[#E5E5E5] font-sans selection:bg-[#10B981] selection:text-[#0A0A0A]">
      <div className="max-w-[1440px] mx-auto px-6 py-24 lg:px-12">
        <header className="mb-20 max-w-3xl">
          <h1 className="text-4xl lg:text-5xl font-medium text-white mb-6 tracking-tight">Research & Methodology</h1>
          <p className="text-xl text-[#999999] leading-relaxed">
            We disclose how our claims are evaluated. We do not participate in generalized marketing leaderboards. Each result is scoped to its evidence and not generalized beyond its conditions.
          </p>
        </header>

        <div className="space-y-6">
          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Methodology Principles</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Framework</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Our evaluation framework is designed to test systems under adversarial enterprise conditions. We prioritize failure-mode discovery over success-case highlighting. Models are assessed on their adherence to constraints, logic preservation, and clear surfacing of uncertainty.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Baseline Comparison Policy</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Standard</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              We compare our deliberation outputs against deterministic heuristics and basic predictive models, rather than unconstrained LLMs. We report relative efficiency gains solely within the context of controlled simulation baselines.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Graph Testing</h3>
              <span className="bg-[#1A1A1A] border border-[#10B981] px-3 py-1 text-[10px] font-mono text-[#10B981] uppercase">Synthetic Data</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Graph propagation algorithms are tested on highly connected, synthetic enterprise topologies designed to simulate massive supply chain networks. They can be evaluated on node-reachability accuracy and loop-detection robustness.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Distribution-Shift Evaluation</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Testing Protocol</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Systems are intentionally subjected to data distribution shifts (e.g., sudden changes in telemetry format or frequency) to evaluate the robustness of the World Model ingestion plane. Performance degrades gracefully by design, halting inference rather than hallucinating state.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Simulation Validation</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Evidence Status</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              The Digital Twin is validated by re-running historical data through the simulation to measure divergence from known historical outcomes. The validity of any forward-looking simulation is strictly bounded by this historical divergence metric.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Multi-Agent Testing</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Testing Protocol</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Deliberation protocols are stress-tested by introducing conflicting, zero-sum constraints to the agent roles. Success is defined not by finding a 'magic' solution, but by the correct invocation of the Decision plane for human resolution when constraints are mathematically irreconcilable.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Calibration & Uncertainty</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Framework</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Outputs from the Intelligence plane must include explicit confidence intervals. We test calibration to ensure that when the system is 'unsure', the output probabilities accurately reflect the empirical likelihood of success.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Safety Constraints</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Evidence Status</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Invariant safety policies are hardcoded into the Decision plane. We test these bounds using adversarial generation designed to intentionally violate policy; the system can be evaluated on its block-rate of these synthetic malicious actions.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-white font-medium">Reproducibility</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Standard</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              All evaluations are designed to be deterministic or statistically reproducible within a bounded margin of error, ensuring that claims made about system behavior can be independently verified under the same conditions.
            </p>
          </div>

          <div className="bg-[#111111] border border-[#262626] p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="text-xl text-[#EF4444] font-medium">Limitations</h3>
              <span className="bg-[#141414] border border-[#262626] px-3 py-1 text-[10px] font-mono text-[#999999] uppercase">Disclosure</span>
            </div>
            <p className="text-[#999999] text-sm leading-relaxed max-w-3xl">
              Cortex does not possess generalized reasoning capabilities outside of its structural design. It cannot autonomously devise novel strategies that break from its predefined action space. Simulation fidelity decreases non-linearly with time horizon extensions.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
