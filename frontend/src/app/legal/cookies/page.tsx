import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Cookie Policy | Cortex',
  description: 'Information regarding the use of cookies and tracking technologies by Cortex.',
};

export default function CookiesPage() {
  return (
    <main className="min-h-screen bg-[#0A0A0A] py-20 px-6">
      <div className="max-w-[1440px] mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12">
        <aside className="lg:col-span-3 hidden lg:block">
          <div className="sticky top-24">
            <h3 className="text-white font-mono text-sm uppercase tracking-wider mb-4 border-b border-[#262626] pb-2">Table of Contents</h3>
            <ul className="space-y-3 text-[#999999] text-sm">
              <li><a href="#essential" className="hover:text-[#10B981] transition-colors">1. Essential Cookies</a></li>
              <li><a href="#optional" className="hover:text-[#10B981] transition-colors">2. Analytics & Optional Cookies</a></li>
              <li><a href="#third-party" className="hover:text-[#10B981] transition-colors">3. Third-Party Cookies</a></li>
              <li><a href="#consent" className="hover:text-[#10B981] transition-colors">4. Consent Controls</a></li>
              <li><a href="#management" className="hover:text-[#10B981] transition-colors">5. How to Manage Cookies</a></li>
              <li><a href="#table" className="hover:text-[#10B981] transition-colors">6. Cookie Table</a></li>
            </ul>
          </div>
        </aside>

        <div className="lg:col-span-8 max-w-[800px] prose prose-invert prose-p:text-[#E5E5E5] prose-headings:text-white prose-a:text-[#10B981]">
          <Link href="/legal" className="text-[#10B981] no-underline hover:underline font-mono text-sm uppercase tracking-wider mb-8 inline-block">← Back to Legal</Link>
          
          <h1 className="text-4xl font-semibold mb-4">Cookie Policy</h1>
          
          <div className="flex gap-4 mb-12 font-mono text-xs uppercase tracking-wider text-[#999999] border-b border-[#262626] pb-6">
            <span>Effective Date: August 16, 2026</span>
            <span>Last Updated: August 16, 2026</span>
            <span>Version: 1.0</span>
            <span>Owner: Privacy Team</span>
          </div>

          <p className="text-[#E5E5E5] leading-relaxed mb-12">
            This Cookie Policy explains how Cortex uses cookies and similar tracking technologies when you visit our website and platform. It clarifies what these technologies are, why we use them, and your rights to control our use of them.
          </p>

          <section id="essential" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">1. Essential Cookies Classification</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Essential cookies are strictly necessary for the platform to function securely and cannot be switched off in our systems. They are usually set in response to actions made by you, such as logging in, setting privacy preferences, or filling out forms. Without these cookies, services you have asked for cannot be provided.
            </p>
          </section>

          <section id="optional" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">2. Optional and Analytics Cookies</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              We use analytics cookies to understand how visitors interact with our platform. These cookies collect information anonymously, reporting website trends without identifying individual visitors. This helps us improve our website's performance and design. These are optional and require your consent.
            </p>
          </section>

          <section id="third-party" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">3. Third-Party Cookies</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              In some cases, we use cookies provided by trusted third parties, such as analytics providers. These third parties may set cookies on your device when you browse our site to deliver their services. We ensure all third-party providers adhere to strict data protection standards.
            </p>
          </section>

          <section id="consent" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">4. Consent Controls Description</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              Upon your first visit to our site, you will be presented with a cookie banner allowing you to accept all cookies, reject non-essential cookies, or manage your specific preferences. You can change these settings at any time via the "Cookie Preferences" link in our website footer.
            </p>
          </section>

          <section id="management" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">5. How to Manage Cookies</h2>
            <p className="text-[#E5E5E5] leading-relaxed mb-4">
              In addition to our on-site consent controls, most web browsers allow you to control cookies through their settings preferences. However, if you limit the ability of websites to set essential cookies, you may worsen your overall user experience and lose the ability to access specific features of the Cortex platform.
            </p>
          </section>

          <section id="table" className="mb-12">
            <h2 className="text-2xl font-semibold mb-4 text-white">6. Cookie Table</h2>
            <div className="overflow-x-auto mt-6">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#262626] text-white">
                    <th className="py-4 px-4 font-semibold">Cookie Name</th>
                    <th className="py-4 px-4 font-semibold">Purpose</th>
                    <th className="py-4 px-4 font-semibold">Type</th>
                    <th className="py-4 px-4 font-semibold">Duration</th>
                  </tr>
                </thead>
                <tbody className="text-[#E5E5E5] text-sm">
                  <tr className="border-b border-[#262626]/50 bg-[#111111]">
                    <td className="py-4 px-4 font-mono text-xs">cortex_session</td>
                    <td className="py-4 px-4">Maintains active user session state</td>
                    <td className="py-4 px-4">Essential</td>
                    <td className="py-4 px-4">Session</td>
                  </tr>
                  <tr className="border-b border-[#262626]/50">
                    <td className="py-4 px-4 font-mono text-xs">cortex_csrf</td>
                    <td className="py-4 px-4">Prevents Cross-Site Request Forgery</td>
                    <td className="py-4 px-4">Essential</td>
                    <td className="py-4 px-4">Session</td>
                  </tr>
                  <tr className="border-b border-[#262626]/50 bg-[#111111]">
                    <td className="py-4 px-4 font-mono text-xs">cookie_consent</td>
                    <td className="py-4 px-4">Stores user cookie preferences</td>
                    <td className="py-4 px-4">Essential</td>
                    <td className="py-4 px-4">1 Year</td>
                  </tr>
                  <tr className="border-b border-[#262626]/50">
                    <td className="py-4 px-4 font-mono text-xs">_ga</td>
                    <td className="py-4 px-4">Distinguishes users for analytics</td>
                    <td className="py-4 px-4">Analytics</td>
                    <td className="py-4 px-4">2 Years</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
