import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Contact | Cortex',
  description: 'Contact Cortex for enterprise, engineering, and security inquiries.',
};

export default function ContactPage() {
  return (
    <div className="min-h-screen bg-[#0A0A0A] text-white">
      <main className="max-w-[1440px] mx-auto px-6 md:px-12 py-24 md:py-32">
        <div className="max-w-3xl">
          <div className="font-mono text-[#10B981] text-xs uppercase tracking-widest mb-6 border-l-2 border-[#10B981] pl-4">
            Cortex / Contact
          </div>
          <h1 className="text-4xl md:text-5xl font-medium tracking-tight mb-8">
            Contact Cortex
          </h1>
          
          <p className="text-lg text-[#E5E5E5] mb-16">
            Please direct your inquiry to the appropriate channel below. We aim to route all communications efficiently and securely.
          </p>

          <div className="space-y-6">
            {/* Enterprise */}
            <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col md:flex-row gap-8 items-start md:items-center">
              <div className="flex-grow">
                <h2 className="text-xl font-medium mb-2">Enterprise & Pilots</h2>
                <p className="text-[#999999]">
                  For inquiries regarding deployment, design partnerships, and operational demonstrations.
                </p>
                <div className="mt-4">
                  <Link href="/demo" className="text-[#10B981] hover:text-[#059669] font-medium inline-flex items-center gap-2">
                    Request a Demonstration <span aria-hidden="true">→</span>
                  </Link>
                </div>
              </div>
              <div className="shrink-0 w-full md:w-auto">
                <a 
                  href="mailto:enterprise@cortex.example.com" 
                  className="block w-full md:w-auto border border-[#262626] bg-[#141414] hover:bg-[#1A1A1A] px-6 py-3 text-center font-mono text-sm transition-colors"
                >
                  enterprise@cortex.example.com
                </a>
              </div>
            </div>

            {/* Engineering */}
            <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col md:flex-row gap-8 items-start md:items-center">
              <div className="flex-grow">
                <h2 className="text-xl font-medium mb-2">Engineering & Research</h2>
                <p className="text-[#999999]">
                  For technical inquiries, collaboration on open standards, and architectural questions.
                </p>
              </div>
              <div className="shrink-0 w-full md:w-auto">
                <a 
                  href="mailto:engineering@cortex.example.com" 
                  className="block w-full md:w-auto border border-[#262626] bg-[#141414] hover:bg-[#1A1A1A] px-6 py-3 text-center font-mono text-sm transition-colors"
                >
                  engineering@cortex.example.com
                </a>
              </div>
            </div>

            {/* Security */}
            <div className="bg-[#111111] border border-[#262626] p-8 flex flex-col md:flex-row gap-8 items-start md:items-center">
              <div className="flex-grow">
                <h2 className="text-xl font-medium mb-2">Security & Disclosures</h2>
                <p className="text-[#999999]">
                  For reporting vulnerabilities or discussing our security posture and compliance protocols.
                </p>
                <div className="mt-4">
                  <Link href="/security/report-vulnerability" className="text-[#10B981] hover:text-[#059669] font-medium inline-flex items-center gap-2">
                    Vulnerability Disclosure Program <span aria-hidden="true">→</span>
                  </Link>
                </div>
              </div>
              <div className="shrink-0 w-full md:w-auto">
                <a 
                  href="mailto:security@cortex.example.com" 
                  className="block w-full md:w-auto border border-[#262626] bg-[#141414] hover:bg-[#1A1A1A] px-6 py-3 text-center font-mono text-sm transition-colors"
                >
                  security@cortex.example.com
                </a>
              </div>
            </div>
          </div>
          
          <div className="mt-16 text-sm text-[#666666]">
            Note: For all inquiries, please share only non-sensitive, necessary information. Do not send proprietary data or credentials through these channels.
          </div>
        </div>
      </main>
    </div>
  );
}
