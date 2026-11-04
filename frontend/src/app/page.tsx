import Link from "next/link";

const workflow = [
  ["01", "Connect", "Bring in BOM, inventory, purchase orders, and production commitments."],
  ["02", "Understand", "Reconstruct the component dependencies behind the disruption."],
  ["03", "Simulate", "Compare recovery options against availability, timing, and cost."],
  ["04", "Decide", "Approve a traceable action with the evidence and assumptions attached."],
];

export default function RootPage() {
  return (
    <main className="min-h-screen bg-bg text-ink">
      <header className="mx-auto flex max-w-7xl items-center justify-between border-b border-border px-6 py-5 lg:px-8">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center bg-accent text-sm font-bold text-white">C</span>
          <span className="text-sm font-semibold tracking-tight">Cortex</span>
        </Link>
        <nav className="flex items-center gap-3 text-xs">
          <Link href="#how-it-works" className="hidden text-ink-secondary hover:text-ink sm:inline">How it works</Link>
          <Link href="/auth/login?next=%2Fnexus%2Fcockpit" className="button-secondary">Sign in</Link>
          <Link href="/auth/signup?next=%2Fnexus%2Fcockpit" className="button-primary">Request access</Link>
        </nav>
      </header>

      <section className="mx-auto grid max-w-7xl gap-12 px-6 pb-20 pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:px-8 lg:pb-28 lg:pt-24">
        <div className="flex flex-col justify-center">
          <p className="eyebrow">Cortex Disruption Intelligence · India-first</p>
          <h1 className="mt-5 max-w-3xl text-4xl font-semibold leading-[1.12] tracking-[-0.045em] sm:text-5xl lg:text-6xl">Make the next supply-chain decision with the whole picture.</h1>
          <p className="mt-6 max-w-2xl text-base leading-7 text-ink-secondary">Cortex connects manufacturing data, traces component dependencies, and evaluates recovery choices when a supplier disruption puts production at risk.</p>
          <div className="mt-8 flex flex-wrap gap-3"><Link href="/auth/signup?next=%2Fnexus%2Fcockpit" className="button-primary">Start with a workspace <span aria-hidden="true">→</span></Link><Link href="#how-it-works" className="button-secondary">See the operating model</Link></div>
          <p className="mt-5 text-[11px] text-ink-muted">A focused operational decision layer above your ERP. Human approval remains required for consequential actions.</p>
        </div>

        <div className="border border-border bg-surface p-5 sm:p-6">
          <div className="flex items-center justify-between border-b border-border pb-4"><div><p className="eyebrow">Illustrative workflow</p><p className="mt-1 text-sm font-medium">Supplier delay · 12 days</p></div><span className="badge badge-neutral">SYNTHETIC EXAMPLE</span></div>
          <div className="space-y-0 divide-y divide-border">
            <div className="grid grid-cols-[auto_1fr_auto] items-center gap-4 py-5"><span className="flex h-9 w-9 items-center justify-center border border-critical/50 text-xs font-semibold text-critical">!</span><div><div className="text-sm font-medium">Critical component delivery moved</div><div className="mt-1 text-xs text-ink-secondary">Supplier commitment changed in the current source data.</div></div><span className="font-mono text-xs text-critical">12d</span></div>
            <div className="py-5"><div className="eyebrow">Cortex traces</div><div className="mt-3 flex flex-wrap items-center gap-2 text-xs"><span className="border border-border px-2 py-1">Supplier</span><span className="text-ink-muted">→</span><span className="border border-accent/50 bg-accent-subtle px-2 py-1">Component</span><span className="text-ink-muted">→</span><span className="border border-border px-2 py-1">BOM</span><span className="text-ink-muted">→</span><span className="border border-border px-2 py-1">Production orders</span></div></div>
            <div className="grid gap-3 py-5 sm:grid-cols-3"><div><div className="eyebrow">Impact</div><div className="mt-2 text-sm">Affected orders</div><div className="mt-1 font-mono text-xs text-ink-muted">Calculated from state</div></div><div><div className="eyebrow">Options</div><div className="mt-2 text-sm">Scenario comparison</div><div className="mt-1 font-mono text-xs text-ink-muted">Constraint checked</div></div><div><div className="eyebrow">Control</div><div className="mt-2 text-sm">Approval required</div><div className="mt-1 font-mono text-xs text-ink-muted">Decision receipt</div></div></div>
          </div>
          <div className="border-t border-border pt-4 text-[11px] text-ink-muted">The example is illustrative. Customer results appear only inside an authorised workspace.</div>
        </div>
      </section>

      <section id="how-it-works" className="border-y border-border bg-surface/40">
        <div className="mx-auto max-w-7xl px-6 py-16 lg:px-8 lg:py-20"><div className="max-w-2xl"><p className="eyebrow">One decision loop</p><h2 className="mt-3 text-2xl font-semibold tracking-tight sm:text-3xl">From fragmented files to a reviewable recovery plan.</h2><p className="mt-3 text-sm leading-6 text-ink-secondary">Cortex is designed for the moment when an operations team needs an answer, not another dashboard to monitor.</p></div><div className="mt-10 grid gap-px border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">{workflow.map(([number, title, detail]) => <div key={number} className="bg-bg p-5"><div className="font-mono text-[10px] text-accent">{number}</div><h3 className="mt-8 text-sm font-semibold">{title}</h3><p className="mt-2 text-xs leading-5 text-ink-secondary">{detail}</p></div>)}</div></div>
      </section>

      <section className="mx-auto grid max-w-7xl gap-10 px-6 py-16 lg:grid-cols-2 lg:px-8 lg:py-20"><div><p className="eyebrow">Built for manufacturing reality</p><h2 className="mt-3 max-w-xl text-2xl font-semibold tracking-tight sm:text-3xl">Use the systems you already have. Add a decision layer where the investigation breaks down.</h2></div><div className="space-y-4 text-sm text-ink-secondary"><div className="border-l-2 border-accent pl-4"><span className="font-medium text-ink">CSV, Excel, and ERP exports</span><p className="mt-1 text-xs leading-5">Start with a defined data contract and visible readiness checks.</p></div><div className="border-l-2 border-accent pl-4"><span className="font-medium text-ink">Deterministic operational calculations</span><p className="mt-1 text-xs leading-5">Inventory, BOM, timing, and financial conclusions stay inspectable.</p></div><div className="border-l-2 border-accent pl-4"><span className="font-medium text-ink">Governed decisions</span><p className="mt-1 text-xs leading-5">Recommendations are proposals. Operators approve, execute, and record outcomes.</p></div></div></section>

      <footer className="border-t border-border"><div className="mx-auto flex max-w-7xl flex-col gap-3 px-6 py-6 text-[11px] text-ink-muted sm:flex-row sm:items-center sm:justify-between lg:px-8"><span>© {new Date().getFullYear()} Cortex</span><span>Operational decision intelligence for complex operations.</span></div></footer>
    </main>
  );
}
