import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Privacy Policy | Cortex',
  description: 'Privacy Policy outlining data processing practices for Cortex.',
};

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-[#0A0A0A] py-20 px-6">
      <div className="max-w-[1440px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12">
        <aside className="lg:col-span-3 hidden lg:block">
          <div className="sticky top-24">
            <h3 className="text-white font-mono text-sm uppercase tracking-wider mb-4 border-b border-[#262626] pb-2">Table of Contents</h3>
            <ul className="space-y-3 text-[#999999] text-sm">
              <li><a href="#roles" className="hover:text-[#10B981] transition-colors">1. Controller & Processor Roles</a></li>
              <li><a href="#data-categories" className="hover:text-[#10B981] transition-colors">2. Data Categories Collected</a></li>
              <li><a href="#purpose" className="hover:text-[#10B981] transition-colors">3. Purpose of Processing</a></li>
              <li><a href="#retention" className="hover:text-[#10B981] transition-colors">4. Retention Policies</a></li>
              <li><a href="#subprocessors" className="hover:text-[#10B981] transition-colors">5. Subprocessors</a></li>
              <li><a href="#individual-rights" className="hover:text-[#10B981] transition-colors">6. Individual Rights</a></li>
              <li><a href="#international-transfers" className="hover:text-[#10B981] transition-colors">7. International Transfers</a></li>
              <li><a href="#demo-requests" className="hover:text-[#10B981] transition-colors">8. Demo Request Data</a></li>
              <li><a href="#cookies" className="hover:text-[#10B981] transition-colors">9. Cookie Reference</a></li>
              <li><a href="#contact" className="hover:text-[#10B981] transition-colors">10. Contact Information</a></li>
            </ul>
          </div>
        </aside>

        <div className="lg:col-span-8 max-w-[800px] prose prose-invert prose-p:text-[#E5E5E5] prose-headings:text-white prose-a:text-[#10B981]">
          <Link href="/legal" className="text-[#10B981] no-underline hover:underline font-mono text-sm uppercase tracking-wider mb-8 inline-block">← Back to Legal</Link>
          
          <h1 className="text-4xl font-semibold mb-4">Privacy Policy</h1>
          
          <div className="flex gap-4 mb-12 font-mono text-xs uppercase tracking-wider text-[#999999] border-b border-[#262626] pb-6">
            <span>Effective Date: August 16, 2026</span>
            <span>Last Updated: August 16, 2026</span>
            <span>Version: 1.0</span>
            <span>Owner: Privacy Team</span>
          </div>

          <section id="roles" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">1. Controller and Processor Roles</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Under applicable data protection laws (including GDPR), Cortex acts as the Data Processor for customer data submitted to our platform for evaluation and operations. The customer acts as the Data Controller. For account management and billing data, Cortex acts as a Data Controller.
            </p>
          </section>

          <section id="data-categories" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">2. Data Categories Collected</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              We collect the following categories of data:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li><strong>Account Information:</strong> Names, email addresses, roles, and authentication credentials.</li>
              <li><strong>Customer Data:</strong> Data submitted by the customer into the platform for processing, which remains under the customer's control.</li>
              <li><strong>Usage Data:</strong> System logs, audit trails, and performance metrics generated through platform use.</li>
              <li><strong>Communication Data:</strong> Support tickets, inquiries, and demo request information.</li>
            </ul>
          </section>

          <section id="purpose" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">3. Purpose of Processing</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              We process data solely for the following purposes:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Providing and maintaining the Cortex platform functionality.</li>
              <li>Enforcing our human-in-the-loop authorization model and maintaining audit logs.</li>
              <li>Ensuring security, preventing abuse, and identifying vulnerabilities.</li>
              <li>Fulfilling contractual obligations and managing customer accounts.</li>
            </ul>
          </section>

          <section id="retention" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">4. Retention Policies</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Customer data is retained only for the duration of the active service contract unless earlier deletion is requested by the controller. Upon contract termination, customer data is securely purged within 30 days. Audit logs and usage data required for compliance and security are retained for a minimum of 12 months.
            </p>
          </section>

          <section id="subprocessors" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">5. Subprocessors</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex utilizes a vetted list of third-party subprocessors to provide infrastructure and specialized services. All subprocessors are subject to strict data processing agreements matching the security standards outlined in this policy. A current list of subprocessors is available upon request.
            </p>
          </section>

          <section id="individual-rights" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">6. Individual Rights</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Depending on your jurisdiction, you have rights regarding your personal data, including:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li><strong>Right to Access:</strong> Requesting copies of your personal data.</li>
              <li><strong>Right to Rectification:</strong> Correcting inaccurate information.</li>
              <li><strong>Right to Erasure:</strong> Requesting deletion of your data (Right to be Forgotten).</li>
              <li><strong>Right to Data Portability:</strong> Receiving your data in a structured, machine-readable format.</li>
            </ul>
          </section>

          <section id="international-transfers" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">7. International Transfers</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              When transferring data originating from the European Economic Area (EEA) to countries lacking an adequacy decision, Cortex relies on Standard Contractual Clauses (SCCs) and implements supplementary technical measures to ensure equivalent protection.
            </p>
          </section>

          <section id="demo-requests" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">8. Demo Request Data Handling</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Information submitted via demo request forms is used exclusively to contact you regarding the Cortex platform and schedule controlled demonstrations. This data is not sold to third parties and is retained only as long as necessary to facilitate the requested engagement.
            </p>
          </section>

          <section id="cookies" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">9. Cookie Reference</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Our use of tracking technologies is detailed separately. For complete information on how we utilize these technologies, please refer to our <Link href="/legal/cookies">Cookie Policy</Link>.
            </p>
          </section>

          <section id="contact" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">10. Contact Information</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              For privacy-related inquiries, data subject requests, or questions regarding this policy, please contact our Data Protection Officer at: <br/><br/>
              <span className="font-mono text-[#10B981]">privacy@cortex.test</span>
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
