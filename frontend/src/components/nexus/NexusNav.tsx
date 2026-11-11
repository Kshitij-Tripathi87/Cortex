"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Cortex Nexus — canonical navigation (demo spec §3).
 *
 * Every entry resolves to a real authenticated surface backed by the
 * canonical `/nexus/*` API; there are no decorative links (spec: no fake
 * surfaces). Group active state follows the pathname; child entries are
 * in-page views selected by query/hash.
 */

interface NavChild {
  label: string;
  href: string;
}

interface NavGroup {
  label: string;
  href: string;
  children?: NavChild[];
}

const NAV_GROUPS: NavGroup[] = [
  { label: "Command Center", href: "/nexus/cockpit" },
  {
    label: "World State",
    href: "/nexus/world",
    children: [
      { label: "Entity Explorer", href: "/nexus/world?view=explorer" },
      { label: "Dependency Graph", href: "/nexus/world?view=graph" },
      { label: "Data Quality", href: "/nexus/world?view=quality" },
      { label: "Source Provenance", href: "/nexus/world?view=provenance" },
    ],
  },
  {
    label: "Intelligence",
    href: "/nexus/impact",
    children: [
      { label: "Disruptions", href: "/nexus/impact?view=detail" },
      { label: "Impact Analysis", href: "/nexus/impact?view=detail" },
      { label: "Risk & Blast Radius", href: "/nexus/impact?view=paths" },
    ],
  },
  {
    label: "Scenario Studio",
    href: "/nexus/scenarios",
    children: [
      { label: "Recovery Options", href: "/nexus/scenarios#options" },
      { label: "Simulation Results", href: "/nexus/scenarios#results" },
      { label: "Scenario Comparison", href: "/nexus/scenarios#comparison" },
    ],
  },
  {
    label: "Decision Room",
    href: "/nexus/decision-room",
    children: [
      { label: "Pending Decisions", href: "/nexus/decision-room?phase=awaiting_approval" },
      { label: "Approvals", href: "/nexus/decision-room?phase=approved" },
      { label: "Decision History", href: "/nexus/decision-room#receipt" },
    ],
  },
  {
    label: "Operations",
    href: "/nexus/operations",
    children: [
      { label: "Ingestion Jobs", href: "/upload" },
      { label: "Audit Events", href: "/nexus/operations#audit" },
      { label: "System Health", href: "/nexus/operations#health" },
    ],
  },
];

function isActive(pathname: string, href: string): boolean {
  if (pathname === href) return true;
  return pathname.startsWith(`${href}/`);
}

export default function NexusNav() {
  const pathname = usePathname();

  const links = (compact = false) => (
    <nav className={compact ? "flex items-center gap-1 overflow-x-auto px-3 py-2" : "space-y-1 px-3"}>
      {NAV_GROUPS.map((group) => {
        const active = isActive(pathname, group.href);
        return (
          <div key={group.label} className={compact ? "shrink-0" : ""}>
            <Link
              href={group.href}
              className={`block border-l-2 px-3 py-2 text-sm transition-colors ${
                compact ? "border-0 whitespace-nowrap" : ""
              } ${
                active
                  ? "border-accent bg-surface-2 text-ink"
                  : "border-transparent text-ink-secondary hover:bg-surface hover:text-ink"
              }`}
            >
              {group.label}
            </Link>
            {group.children && !compact && (
              <div className="mb-2 ml-3 space-y-0.5 border-l border-border pl-3">
                {group.children.map((child) => (
                  <Link
                    key={child.label}
                    href={child.href}
                    className="block px-2 py-1 font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted transition-colors hover:text-ink"
                  >
                    {child.label}
                  </Link>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden w-[232px] shrink-0 flex-col border-r border-border bg-surface/40 py-5 lg:flex">
        <Link href="/" className="mb-8 flex items-center gap-2 px-5">
          <span className="flex h-7 w-7 items-center justify-center bg-accent text-sm font-bold text-white">C</span>
          <span className="text-sm font-semibold tracking-tight">Cortex Nexus</span>
        </Link>
        {links()}
        <div className="mt-auto border-t border-border px-5 pt-4">
          <p className="font-mono text-[9px] uppercase tracking-[0.12em] text-ink-muted">
            Canonical operational surface
          </p>
          <p className="mt-1 text-[10px] text-ink-muted">Evidence-backed · approval-gated</p>
        </div>
      </aside>

      {/* Mobile / narrow top navigation */}
      <div className="border-b border-border bg-surface/60 lg:hidden">
        <div className="flex items-center gap-2 px-3 pt-3">
          <span className="flex h-6 w-6 items-center justify-center bg-accent text-xs font-bold text-white">C</span>
          <span className="text-sm font-semibold tracking-tight">Cortex Nexus</span>
        </div>
        {links(true)}
      </div>
    </>
  );
}
