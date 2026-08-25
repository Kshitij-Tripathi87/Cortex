import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Legal & Governance | Cortex',
  description: 'Legal policies, governance documentation, and compliance information for Cortex.',
};

const legalDocs = [
  {
    title: 'Terms of Service',
    description: 'The primary agreement governing your use of Cortex services, including service scope, limitations, and obligations.',
    href: '/legal/terms',
    date: 'August 16, 2026',
    version: '1.0'
  },
  {
    title: 'Privacy Policy',
    description: 'How we collect, use, process, and protect your data, including roles, retention, and individual rights.',
    href: '/legal/privacy',
    date: 'August 16, 2026',
    version: '1.0'
  },
  {
    title: 'Acceptable Use Policy',
    description: 'Guidelines on permitted and prohibited uses of the Cortex platform to ensure security and prevent abuse.',
    href: '/legal/acceptable-use',
    date: 'August 16, 2026',
    version: '1.0'
  },
  {
    title: 'Responsible AI Policy',
    description: 'Our principles and operational rules for AI governance, emphasizing grounded evidence and human control.',
    href: '/legal/responsible-ai',
    date: 'August 16, 2026',
    version: '1.0'
  },
  {
    title: 'Cookie Policy',
    description: 'Information about how we use cookies and similar technologies to ensure platform functionality and analyze usage.',
    href: '/legal/cookies',
    date: 'August 16, 2026',
    version: '1.0'
  }
];

export default function LegalPage() {
  return (
    <main className="min-h-screen bg-[#0A0A0A] py-20 px-6">
      <div className="max-w-[1440px] mx-auto">
        <header className="mb-16 max-w-[800px]">
          <h1 className="text-4xl md:text-5xl font-semibold text-white mb-6">Legal & Governance</h1>
          <p className="text-[#E5E5E5] text-lg leading-relaxed">
            These documents govern your use of the Cortex platform and outline our commitments to security, privacy, and responsible AI operations.
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
          {legalDocs.map((doc) => (
            <Link 
              key={doc.href} 
              href={doc.href}
              className="block bg-[#111111] border border-[#262626] p-8 hover:border-[#10B981] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#10B981]"
            >
              <div className="flex justify-between items-start mb-4">
                <h2 className="text-xl font-semibold text-white">{doc.title}</h2>
                <span className="text-[#10B981] font-mono text-xs px-2 py-1 bg-[#10B981]/10 uppercase tracking-wider">v{doc.version}</span>
              </div>
              <p className="text-[#999999] mb-6 leading-relaxed">
                {doc.description}
              </p>
              <div className="text-xs text-[#999999] font-mono uppercase tracking-wider">
                Effective: {doc.date}
              </div>
            </Link>
          ))}
        </div>

        <section className="bg-[#111111] border border-[#262626] p-8 max-w-[800px]">
          <h2 className="text-xl font-semibold text-white mb-4">Vulnerability Disclosure</h2>
          <p className="text-[#999999] mb-6 leading-relaxed">
            Security is critical to our operations. If you believe you have discovered a vulnerability in a Cortex product or service, please report it to our security team. We ask that you do not publicly disclose the issue until we have had an opportunity to address it.
          </p>
          <Link href="mailto:security@cortex.test" className="inline-flex items-center text-[#10B981] hover:text-[#10B981]/80 font-medium transition-colors">
            Report a Vulnerability →
          </Link>
        </section>
      </div>
    </main>
  );
}
