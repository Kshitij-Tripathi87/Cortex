import React from 'react';
import Link from 'next/link';

export default function Footer() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-[#0A0A0A] border-t border-[#262626] mt-auto pt-16 pb-8">
      <div className="max-w-[1440px] mx-auto px-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-16">
          <div className="col-span-1">
            <Link href="/" className="text-white font-mono tracking-[0.25em] font-semibold text-sm hover:text-[#10B981] transition-colors inline-block mb-4">
              CORTEX
            </Link>
            <p className="text-[#999999] text-sm leading-relaxed pr-8">
              Operational intelligence for complex enterprises.
            </p>
          </div>

          <div className="col-span-1">
            <h3 className="text-white font-mono text-xs uppercase tracking-wider mb-4">Technology</h3>
            <ul className="space-y-3">
              <li><Link href="/platform" className="text-[#999999] hover:text-white text-sm transition-colors">Platform</Link></li>
              <li><Link href="/intelligence" className="text-[#999999] hover:text-white text-sm transition-colors">Intelligence</Link></li>
              <li><Link href="/enterprise" className="text-[#999999] hover:text-white text-sm transition-colors">Enterprise</Link></li>
              <li><Link href="/research" className="text-[#999999] hover:text-white text-sm transition-colors">Research</Link></li>
            </ul>
          </div>

          <div className="col-span-1">
            <h3 className="text-white font-mono text-xs uppercase tracking-wider mb-4">Company</h3>
            <ul className="space-y-3">
              <li><Link href="/company" className="text-[#999999] hover:text-white text-sm transition-colors">About Cortex</Link></li>
              <li><Link href="/contact" className="text-[#999999] hover:text-white text-sm transition-colors">Contact</Link></li>
              <li><Link href="/demo" className="text-[#999999] hover:text-white text-sm transition-colors">Request a Demo</Link></li>
            </ul>
          </div>

          <div className="col-span-1">
            <h3 className="text-white font-mono text-xs uppercase tracking-wider mb-4">Trust &amp; Legal</h3>
            <ul className="space-y-3">
              <li><Link href="/security" className="text-[#999999] hover:text-white text-sm transition-colors">Security</Link></li>
              <li><Link href="/legal/privacy" className="text-[#999999] hover:text-white text-sm transition-colors">Privacy Policy</Link></li>
              <li><Link href="/legal/terms" className="text-[#999999] hover:text-white text-sm transition-colors">Terms of Service</Link></li>
              <li><Link href="/legal/responsible-ai" className="text-[#999999] hover:text-white text-sm transition-colors">Responsible AI</Link></li>
              <li><Link href="/legal/acceptable-use" className="text-[#999999] hover:text-white text-sm transition-colors">Acceptable Use</Link></li>
              <li><Link href="/legal/cookies" className="text-[#999999] hover:text-white text-sm transition-colors">Cookies</Link></li>
              <li><Link href="/security/report-vulnerability" className="text-[#999999] hover:text-white text-sm transition-colors">Vulnerability Disclosure</Link></li>
            </ul>
          </div>
        </div>

        <div className="pt-8 border-t border-[#262626] flex flex-col md:flex-row items-center justify-between gap-4">
          <p className="text-[#666666] text-xs">
            &copy; {currentYear} Cortex Operations, Inc. All rights reserved.
          </p>
          <div className="flex items-center space-x-6">
            <Link href="/security" className="text-[#666666] hover:text-[#999999] text-xs transition-colors flex items-center gap-2">
              <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M2.166 4.999A11.954 11.954 0 0010 1.944 11.954 11.954 0 0017.834 5c.11.65.166 1.32.166 2.001 0 5.225-3.34 9.67-8 11.317C5.34 16.67 2 12.225 2 7c0-.682.057-1.35.166-2.001zm11.541 3.708a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              Security
            </Link>
            <Link href="/legal" className="text-[#666666] hover:text-[#999999] text-xs transition-colors">
              Legal
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
