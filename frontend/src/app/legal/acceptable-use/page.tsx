import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Acceptable Use Policy | Cortex',
  description: 'Acceptable Use Policy defining permitted and prohibited actions on the Cortex platform.',
};

export default function AcceptableUsePage() {
  return (
    <main className="min-h-screen bg-[#0A0A0A] py-20 px-6">
      <div className="max-w-[1440px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12">
        <aside className="lg:col-span-3 hidden lg:block">
          <div className="sticky top-24">
            <h3 className="text-white font-mono text-sm uppercase tracking-wider mb-4 border-b border-[#262626] pb-2">Table of Contents</h3>
            <ul className="space-y-3 text-[#999999] text-sm">
              <li><a href="#prohibited-data" className="hover:text-[#10B981] transition-colors">1. Prohibited Data Types</a></li>
              <li><a href="#abuse-prevention" className="hover:text-[#10B981] transition-colors">2. Abuse Prevention</a></li>
              <li><a href="#unauthorized-access" className="hover:text-[#10B981] transition-colors">3. Unauthorized Access</a></li>
              <li><a href="#prohibited-automation" className="hover:text-[#10B981] transition-colors">4. Prohibited Automation</a></li>
              <li><a href="#account-responsibilities" className="hover:text-[#10B981] transition-colors">5. Account Responsibilities</a></li>
              <li><a href="#consequences" className="hover:text-[#10B981] transition-colors">6. Consequences of Violation</a></li>
            </ul>
          </div>
        </aside>

        <div className="lg:col-span-8 max-w-[800px] prose prose-invert prose-p:text-[#E5E5E5] prose-headings:text-white prose-a:text-[#10B981]">
          <Link href="/legal" className="text-[#10B981] no-underline hover:underline font-mono text-sm uppercase tracking-wider mb-8 inline-block">← Back to Legal</Link>
          
          <h1 className="text-4xl font-semibold mb-4">Acceptable Use Policy</h1>
          
          <div className="flex gap-4 mb-12 font-mono text-xs uppercase tracking-wider text-[#999999] border-b border-[#262626] pb-6">
            <span>Effective Date: August 16, 2026</span>
            <span>Last Updated: August 16, 2026</span>
            <span>Version: 1.0</span>
            <span>Owner: Security Team</span>
          </div>

          <p className="text-[#E5E5E5] leading-relaxed mb-12">
            This Acceptable Use Policy ("AUP") outlines the permissible uses of the Cortex platform. By accessing or using our services, you agree to comply with this policy. Cortex is designed to provide secure, human-controlled evaluation environments.
          </p>

          <section id="prohibited-data" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">1. Prohibited Data Types</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Users may not submit, process, or store the following types of data on the Cortex platform:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Classified government information or highly restricted defense data.</li>
              <li>Malware, viruses, trojans, or any malicious code intended to disrupt systems.</li>
              <li>Data that infringes upon the intellectual property rights of third parties.</li>
              <li>Illegal content, including materials related to child exploitation or terrorism.</li>
            </ul>
          </section>

          <section id="abuse-prevention" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">2. Abuse Prevention</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              You agree not to use the Cortex platform to:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Interfere with or disrupt the integrity or performance of the service.</li>
              <li>Attempt to bypass or disable any security mechanism or access controls.</li>
              <li>Perform load testing, penetration testing, or vulnerability scanning without explicit prior written authorization from Cortex.</li>
              <li>Generate or distribute unsolicited communications (spam).</li>
            </ul>
          </section>

          <section id="unauthorized-access" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">3. Unauthorized Access</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Access to the platform is restricted to authorized personnel. You must not:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Share authentication credentials with unauthorized users.</li>
              <li>Attempt to access data, environments, or accounts belonging to other customers.</li>
              <li>Reverse engineer, decompile, or extract the source code of the Cortex platform.</li>
            </ul>
          </section>

          <section id="prohibited-automation" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">4. Prohibited Automation</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Cortex enforces a strict human-in-the-loop authorization requirement. You may not:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Utilize scripts, bots, or external systems to automatically approve actions within the platform without human review.</li>
              <li>Attempt to grant the platform autonomous execution authority over external systems.</li>
              <li>Circumvent the platform's mandatory review and authorization checkpoints.</li>
            </ul>
          </section>

          <section id="account-responsibilities" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">5. Account Responsibilities</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Customers are fully responsible for all activities occurring under their accounts. You must implement appropriate internal controls to ensure that only trained, authorized personnel evaluate platform outputs and approve actions.
            </p>
          </section>

          <section id="consequences" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">6. Consequences of Violation</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Violations of this Acceptable Use Policy may result in immediate action, including but not limited to:
            </p>
            <ul className="text-[#E5E5E5] list-disc pl-6 space-y-2 mb-4 marker:text-[#262626]">
              <li>Temporary suspension of account access.</li>
              <li>Permanent termination of services without refund.</li>
              <li>Deletion of offending data.</li>
              <li>Notification of appropriate legal or regulatory authorities in cases of severe abuse or illegal activity.</li>
            </ul>
          </section>
        </div>
      </div>
    </main>
  );
}
