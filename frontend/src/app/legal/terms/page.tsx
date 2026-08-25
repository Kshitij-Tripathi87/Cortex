import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Terms of Service | Cortex',
  description: 'Terms of Service governing the use of the Cortex platform.',
};

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-[#0A0A0A] py-20 px-6">
      <div className="max-w-[1440px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12">
        <aside className="lg:col-span-3 hidden lg:block">
          <div className="sticky top-24">
            <h3 className="text-white font-mono text-sm uppercase tracking-wider mb-4 border-b border-[#262626] pb-2">Table of Contents</h3>
            <ul className="space-y-3 text-[#999999] text-sm">
              <li><a href="#service-scope" className="hover:text-[#10B981] transition-colors">1. Service Scope and Description</a></li>
              <li><a href="#authorization" className="hover:text-[#10B981] transition-colors">2. Authorization Model</a></li>
              <li><a href="#customer-obligations" className="hover:text-[#10B981] transition-colors">3. Customer Obligations</a></li>
              <li><a href="#limitations" className="hover:text-[#10B981] transition-colors">4. Limitations of Service</a></li>
              <li><a href="#suspension" className="hover:text-[#10B981] transition-colors">5. Suspension and Termination</a></li>
              <li><a href="#confidentiality" className="hover:text-[#10B981] transition-colors">6. Confidentiality</a></li>
              <li><a href="#liability" className="hover:text-[#10B981] transition-colors">7. Liability Framework</a></li>
              <li><a href="#intellectual-property" className="hover:text-[#10B981] transition-colors">8. Intellectual Property</a></li>
              <li><a href="#data-ownership" className="hover:text-[#10B981] transition-colors">9. Data Ownership</a></li>
              <li><a href="#governing-law" className="hover:text-[#10B981] transition-colors">10. Governing Law</a></li>
            </ul>
          </div>
        </aside>

        <div className="lg:col-span-8 max-w-[800px] prose prose-invert prose-p:text-[#E5E5E5] prose-headings:text-white prose-a:text-[#10B981]">
          <Link href="/legal" className="text-[#10B981] no-underline hover:underline font-mono text-sm uppercase tracking-wider mb-8 inline-block">← Back to Legal</Link>
          
          <h1 className="text-4xl font-semibold mb-4">Terms of Service</h1>
          
          <div className="flex gap-4 mb-12 font-mono text-xs uppercase tracking-wider text-[#999999] border-b border-[#262626] pb-6">
            <span>Effective Date: August 16, 2026</span>
            <span>Last Updated: August 16, 2026</span>
            <span>Version: 1.0</span>
            <span>Owner: Legal Team</span>
          </div>

          <section id="service-scope" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">1. Service Scope and Description</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex provides a platform designed to facilitate controlled environment evaluations and operations. The platform offers capabilities for data analysis, system integration, and workflow orchestration. These Terms of Service ("Terms") govern your access to and use of the Cortex services.
            </p>
          </section>

          <section id="authorization" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">2. Authorization Model</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex operates under a strict human-in-the-loop authorization model. Under no circumstances do the platform's systems possess autonomous execution authority over customer environments. All substantive actions require explicit, verifiable human approval prior to execution. The customer is solely responsible for granting, managing, and revoking authorizations.
            </p>
          </section>

          <section id="customer-obligations" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">3. Customer Obligations</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Customers must utilize the service in compliance with all applicable laws and regulations. You are responsible for maintaining the security of your account credentials, reviewing platform recommendations prior to approval, and ensuring your data inputs do not violate our Acceptable Use Policy.
            </p>
          </section>

          <section id="limitations" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">4. Limitations of Service</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              While the platform is designed to provide highly accurate analyses, all outputs must be evaluated by qualified personnel. Demonstrations provided during onboarding or marketing are synthetic and controlled. The service is provided "as is" and Cortex disclaims any warranty that the service will be uninterrupted or error-free.
            </p>
          </section>

          <section id="suspension" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">5. Suspension and Termination</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex reserves the right to suspend or terminate access to the service immediately if we reasonably believe you have violated these Terms, compromised the security of the platform, or engaged in fraudulent activity. Customers may terminate this agreement at any time by providing written notice.
            </p>
          </section>

          <section id="confidentiality" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">6. Confidentiality</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Both parties agree to maintain the confidentiality of proprietary information disclosed during the term of service. "Confidential Information" includes customer data, platform source code, and business methodologies. Exceptions apply to publicly available information or disclosures required by law.
            </p>
          </section>

          <section id="liability" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">7. Liability Framework and Limitations</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              To the maximum extent permitted by law, Cortex's total aggregate liability arising out of or related to these terms shall not exceed the total amount paid by the customer for the service in the twelve (12) months preceding the incident giving rise to the liability. Neither party shall be liable for indirect, special, incidental, or consequential damages.
            </p>
          </section>

          <section id="intellectual-property" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">8. Intellectual Property</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex retains all rights, title, and interest in and to the platform, including all associated intellectual property rights. The customer is granted a limited, non-exclusive, non-transferable license to use the platform during the term of the agreement.
            </p>
          </section>

          <section id="data-ownership" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">9. Data Ownership</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              The customer retains all right, title, and interest in all customer data provided to the platform. Cortex does not claim ownership over customer data. By submitting data, the customer grants Cortex a limited license strictly to process the data as necessary to provide the service.
            </p>
          </section>

          <section id="governing-law" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">10. Governing Law</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              These Terms shall be governed by and construed in accordance with the laws of [Jurisdiction Placeholder], without regard to its conflict of law provisions. Any disputes arising out of these Terms shall be subject to the exclusive jurisdiction of the courts located in [Location Placeholder].
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
