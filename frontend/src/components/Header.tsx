'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function Header() {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navLinks = [
    { name: 'Platform', href: '/platform' },
    { name: 'Intelligence', href: '/intelligence' },
    { name: 'Enterprise', href: '/enterprise' },
    { name: 'Research', href: '/research' },
    { name: 'Company', href: '/company' },
  ];

  return (
    <header className="h-16 bg-canvas border-b border-line sticky top-0 z-40 w-full">
      <div className="max-w-[1440px] mx-auto px-6 h-full flex items-center justify-between">
        <div className="flex items-center">
          <Link href="/" className="text-ink font-mono tracking-[0.25em] font-semibold text-sm hover:text-accent transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-canvas">
            CORTEX
          </Link>
        </div>

        {/* Desktop Nav */}
        <nav className="hidden md:flex items-center space-x-8">
          {navLinks.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.name}
                href={link.href}
                className={`text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent ${
                  isActive ? 'text-ink' : 'text-muted hover:text-ink'
                }`}
              >
                {link.name}
              </Link>
            );
          })}
        </nav>

        <div className="hidden md:flex items-center">
          <Link
            href="/demo"
            className="bg-accent hover:bg-accent-hover text-white text-sm font-semibold px-4 py-2 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
          >
            Request a demo
          </Link>
        </div>

        {/* Mobile Nav Toggle */}
        <button
          className="md:hidden text-muted hover:text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent p-2"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle mobile menu"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {mobileMenuOpen ? (
              <path strokeLinecap="square" strokeLinejoin="miter" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            ) : (
              <path strokeLinecap="square" strokeLinejoin="miter" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            )}
          </svg>
        </button>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className="md:hidden bg-surface border-b border-line px-6 py-4 space-y-4">
          <nav className="flex flex-col space-y-4">
            {navLinks.map((link) => (
              <Link
                key={link.name}
                href={link.href}
                className="text-muted hover:text-ink text-sm font-medium"
                onClick={() => setMobileMenuOpen(false)}
              >
                {link.name}
              </Link>
            ))}
            <Link
              href="/demo"
              className="text-accent hover:text-accent-hover text-sm font-medium pt-2 border-t border-line inline-block"
              onClick={() => setMobileMenuOpen(false)}
            >
              Request a demo
            </Link>
          </nav>
        </div>
      )}
    </header>
  );
}
