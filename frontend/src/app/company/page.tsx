import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Company | Cortex',
  description: 'Our mission and operating principles for building the decision layer for complex operations.',
};

export default function CompanyPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <main className="max-w-[1440px] mx-auto px-6 md:px-12 py-24 md:py-32">
        <div className="max-w-4xl">
          <div className="font-mono text-[#10B981] text-xs uppercase tracking-widest mb-6 border-l-2 border-[#10B981] pl-4">
            Cortex / Company
          </div>
          <h1 className="text-4xl md:text-5xl font-medium tracking-tight mb-8">
            Building the Decision Layer for Complex Operations
          </h1>
          
          <div className="prose prose-invert max-w-none text-lg text-[#E5E5E5] leading-relaxed mb-24">
            <p>
              Modern enterprise operations face compounding complexity. The systems designed to manage this complexity have instead proliferated it, scattering truth across thousands of disjointed records, logs, and interfaces. Cortex is engineered to synthesize this operational data into a unified, actionable intelligence layer.
            </p>
            <p>
              We believe that the next evolution of operational software is not another dashboard, but an active decision layer—a system designed to propose, simulate, and execute actions under explicit human authority.
            </p>
          </div>

          <div className="mb-24">
            <h2 className="text-2xl font-medium mb-12 border-b border-[#262626] pb-4">Operating Principles</h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Principle 1 */}
              <div className="bg-[#141414] border border-[#262626] p-8 flex flex-col">
                <div className="font-mono text-[#999999] mb-4 text-sm">01</div>
                <h3 className="text-xl font-medium mb-4">Grounded Truth</h3>
                <p className="text-[#999999] leading-relaxed flex-grow">
                  Decisions are only as reliable as the data they rest upon. Cortex prioritizes verifiable data lineage and rigorous grounding. Every proposed action can be traced back to its underlying sources, ensuring operational reality dictates systemic response.
                </p>
              </div>

              {/* Principle 2 */}
              <div className="bg-[#141414] border border-[#262626] p-8 flex flex-col">
                <div className="font-mono text-[#999999] mb-4 text-sm">02</div>
                <h3 className="text-xl font-medium mb-4">Evaluate Before Action</h3>
                <p className="text-[#999999] leading-relaxed flex-grow">
                  Action without foresight is a liability. Our architecture demands that critical proposals pass through simulation and impact evaluation before execution. The system is designed to predict secondary effects, allowing operators to understand consequence before committing.
                </p>
              </div>

              {/* Principle 3 */}
              <div className="bg-[#141414] border border-[#262626] p-8 flex flex-col">
                <div className="font-mono text-[#999999] mb-4 text-sm">03</div>
                <h3 className="text-xl font-medium mb-4">Explicit Authority Boundaries</h3>
                <p className="text-[#999999] leading-relaxed flex-grow">
                  The system does not possess autonomy. All actions are strictly gated by human-defined policy and approval requirements. Cortex augments human operational capability; it never supersedes human authority.
                </p>
              </div>

              {/* Principle 4 */}
              <div className="bg-[#141414] border border-[#262626] p-8 flex flex-col">
                <div className="font-mono text-[#999999] mb-4 text-sm">04</div>
                <h3 className="text-xl font-medium mb-4">Learn from Outcomes</h3>
                <p className="text-[#999999] leading-relaxed flex-grow">
                  Operational environments are non-stationary. Cortex is built to incorporate feedback from executed actions, allowing internal heuristics and evaluation mechanisms to adapt alongside the evolving constraints of the enterprise.
                </p>
              </div>
            </div>
          </div>

          {/* Contact Path */}
          <div className="bg-[#111111] border border-[#262626] p-8 lg:p-12">
            <h2 className="text-2xl font-medium mb-6">Engage with Cortex</h2>
            <p className="text-[#999999] mb-8 max-w-2xl">
              We are currently onboarding select design partners facing distinct operational complexities. If your organization is evaluating new capabilities in this domain, we are open to discussion.
            </p>
            <div className="flex flex-col sm:flex-row gap-4">
              <Link 
                href="/demo" 
                className="bg-[#10B981] hover:bg-[#059669] text-white px-6 py-3 text-center font-medium transition-colors"
              >
                Request Briefing
              </Link>
              <Link 
                href="/contact" 
                className="border border-[#262626] hover:bg-[#1A1A1A] text-white px-6 py-3 text-center font-medium transition-colors"
              >
                View Contact Channels
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
