import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Security Architecture | Cortex',
  description: 'Detailed overview of the Cortex security posture, tenant isolation, and policy enforcement mechanisms.',
};

export default function SecurityPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <main className="max-w-[1440px] mx-auto px-6 md:px-12 py-24 md:py-32">
        <div className="max-w-4xl">
          <div className="font-mono text-[#10B981] text-xs uppercase tracking-widest mb-6 border-l-2 border-[#10B981] pl-4">
            Cortex / Security
          </div>
          <h1 className="text-4xl md:text-5xl font-medium tracking-tight mb-8">
            Security Architecture
          </h1>
          
          <p className="text-lg text-[#E5E5E5] mb-16 max-w-3xl leading-relaxed">
            The Cortex platform is designed to enforce rigorous security controls across all layers of the operational stack. We operate under the assumption that systems operating within enterprise networks must be bounded, auditable, and constrained by explicit policy.
          </p>

          <div className="bg-[#111111] border border-[#262626] p-8 md:p-12 mb-20 overflow-x-auto">
            <h2 className="text-sm font-mono text-[#999999] mb-6 uppercase tracking-wider">Execution Pipeline</h2>
            <div className="whitespace-nowrap font-mono text-sm flex items-center space-x-2 text-[#E5E5E5]">
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2">Agent proposes</span>
              <span className="text-[#666666]">→</span>
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2 text-[#10B981]">Policy evaluates</span>
              <span className="text-[#666666]">→</span>
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2">Simulation tests</span>
              <span className="text-[#666666]">→</span>
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2 text-[#10B981]">Human approves</span>
              <span className="text-[#666666]">→</span>
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2">Execution performs</span>
              <span className="text-[#666666]">→</span>
              <span className="bg-[#1A1A1A] border border-[#262626] px-3 py-2">Audit records</span>
            </div>
          </div>

          <div className="space-y-16">
            
            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Tenant Isolation</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                Cortex architecture is designed to enforce strict logical isolation between tenants. Compute instances and storage volumes are dedicated per tenant in managed deployments. Data cross-contamination is prevented via namespace isolation and rigorous network policies.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Authentication & Authorization</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                Access to the platform requires integration with enterprise identity providers via SAML 2.0 or OIDC. Internal service-to-service communication is authenticated using mutual TLS (mTLS). Role-Based Access Control (RBAC) dictates the limits of user permissions, mapping directly to operational scopes.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Encryption</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                All data is encrypted in transit using TLS 1.3. Data at rest is encrypted using AES-256 block-level encryption. Customers can be configured to manage their own keys via AWS KMS or HashiCorp Vault integrations.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Auditability</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                Every API call, user login, policy change, and execution event is recorded in a tamper-evident, append-only log. This log can be continuously exported to enterprise SIEM systems (e.g., Splunk, Datadog) for comprehensive monitoring and retention compliance.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Agent Capability Boundaries & Policy Enforcement</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                The agent layer cannot execute commands outside of explicitly whitelisted integrations. Policies define exact boundary conditions (e.g., maximum financial exposure, time-of-day restrictions, required human-in-the-loop quorums). If an action violates policy, it is dropped prior to the simulation stage.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Simulation & Approval Gates</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                Proposed actions undergo simulation against a shadow state to predict impact. Execution cannot occur unless the simulation falls within accepted variance bounds and receives cryptographic approval from authorized human operators, preventing runaway automation.
              </p>
            </section>

            <section>
              <h2 className="text-2xl font-medium mb-6 pb-2 border-b border-[#262626]">Customer Shared Responsibilities</h2>
              <p className="text-[#999999] leading-relaxed mb-4">
                While Cortex is responsible for the security of the infrastructure and platform, customers are responsible for managing their internal IAM integrations, defining correct operational policies, and maintaining the security of the end-user devices interacting with Cortex interfaces.
              </p>
            </section>

          </div>

          <div className="mt-24 p-8 border border-[#262626] bg-[#111111]">
            <h2 className="text-xl font-medium mb-4">Incident Reporting & Contact</h2>
            <p className="text-[#999999] mb-6">
              If you have discovered a potential security vulnerability within Cortex systems, please report it immediately through our coordinated disclosure process.
            </p>
            <Link 
              href="/security/report-vulnerability" 
              className="inline-block bg-[#1A1A1A] hover:bg-[#262626] border border-[#262626] text-white px-6 py-3 font-mono text-sm transition-colors"
            >
              Vulnerability Disclosure Program →
            </Link>
          </div>

        </div>
      </main>
    </div>
  );
}
