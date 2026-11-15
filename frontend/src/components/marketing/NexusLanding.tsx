"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

const stages = [
  {
    index: "01",
    label: "INGEST",
    title: "Bring every source into one frame.",
    body: "Connect operational files and systems without losing the context, origin, or history behind each record.",
    detail: "SOURCE DATA  /  IMMUTABLE INPUTS",
  },
  {
    index: "02",
    label: "RECONCILE",
    title: "Resolve identity before you reason.",
    body: "Map records to a shared operational language. Keep claims, evidence, conflicts, and human review visible.",
    detail: "CANONICAL MODEL  /  EVIDENCE LINEAGE",
  },
  {
    index: "03",
    label: "UNDERSTAND",
    title: "Trace what changes across the network.",
    body: "Connect entities and dependencies to surface risk, signals, and the operational consequences of change.",
    detail: "WORLD STATE  /  DEPENDENCY GRAPH",
  },
  {
    index: "04",
    label: "DECIDE",
    title: "Compare paths before taking action.",
    body: "Explore scenarios and recommendations with their assumptions and evidence attached. Keep people in control.",
    detail: "SIMULATION  /  HUMAN GOVERNANCE",
  },
];

function NetworkField({
  activeStage,
  compact = false,
}: {
  activeStage: number;
  compact?: boolean;
}) {
  return (
    <div
      className={`nx-field ${compact ? "nx-field-compact" : ""}`}
      data-stage={activeStage}
      role="img"
      aria-label="Illustrative operational world-state graph connecting suppliers, facilities, inventory, orders, and signals"
    >
      <div className="nx-field-topline">
        <span>WORLD STATE / SYSTEM MAP</span>
        <span className="nx-field-index">FIG. 01</span>
      </div>
      <svg className="nx-network" viewBox="0 0 640 440" aria-hidden="true">
        <defs>
          <pattern id="nx-grid-pattern" width="32" height="32" patternUnits="userSpaceOnUse">
            <path d="M 32 0 L 0 0 0 32" fill="none" stroke="#e9e7e3" strokeWidth="1" />
          </pattern>
        </defs>
        <rect x="0" y="0" width="640" height="440" fill="url(#nx-grid-pattern)" />
        <g className="nx-network-lines">
          <path d="M112 101 L254 176 L354 95 L508 154" />
          <path d="M112 101 L150 305 L300 350 L508 154" />
          <path d="M254 176 L300 350 L488 326" />
          <path d="M354 95 L426 245 L488 326" />
          <path d="M150 305 L426 245" />
          <path d="M254 176 L426 245" />
        </g>
        <g className="nx-network-flow">
          <path d="M112 101 L254 176 L426 245 L488 326" />
          <path d="M354 95 L426 245 L508 154" />
        </g>
        <g className="nx-network-labels">
          <text x="70" y="70">SUPPLIERS</text>
          <text x="220" y="145">FACILITIES</text>
          <text x="327" y="65">INVENTORY</text>
          <text x="475" y="124">ORDERS</text>
          <text x="112" y="342">ROUTES</text>
          <text x="465" y="367">SIGNALS</text>
        </g>
        <g className="nx-network-node nx-node-source">
          <circle cx="112" cy="101" r="10" />
          <circle cx="112" cy="101" r="22" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-facility">
          <circle cx="254" cy="176" r="11" />
          <circle cx="254" cy="176" r="23" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-inventory">
          <circle cx="354" cy="95" r="8" />
          <circle cx="354" cy="95" r="19" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-orders">
          <circle cx="508" cy="154" r="9" />
          <circle cx="508" cy="154" r="21" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-routes">
          <circle cx="150" cy="305" r="8" />
          <circle cx="150" cy="305" r="19" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-world">
          <circle cx="300" cy="350" r="12" />
          <circle cx="300" cy="350" r="27" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-signals">
          <circle cx="488" cy="326" r="8" />
          <circle cx="488" cy="326" r="19" className="nx-node-ring" />
        </g>
        <g className="nx-network-node nx-node-link">
          <circle cx="426" cy="245" r="7" />
        </g>
      </svg>
      <div className="nx-field-legend">
        <span><i className="nx-legend-dot" /> CONNECTED ENTITIES</span>
        <span><i className="nx-legend-line" /> TRACEABLE RELATIONSHIPS</span>
      </div>
      <div className="nx-field-caption">ILLUSTRATIVE MODEL — NOT LIVE CUSTOMER DATA</div>
    </div>
  );
}

export default function NexusLanding() {
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const elements = document.querySelectorAll<HTMLElement>(".nx-reveal");
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.14, rootMargin: "0px 0px -5% 0px" },
    );

    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const steps = document.querySelectorAll<HTMLElement>("[data-story-step]");
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];

        if (visible instanceof IntersectionObserverEntry) {
          const nextStage = Number((visible.target as HTMLElement).dataset.storyStep);
          if (Number.isInteger(nextStage)) setActiveStage(nextStage);
        }
      },
      { threshold: [0.15, 0.35, 0.6], rootMargin: "-35% 0px -40% 0px" },
    );

    steps.forEach((step) => observer.observe(step));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const progress = document.querySelector<HTMLElement>(".nx-scroll-progress");
    if (!progress) return;

    let frame = 0;
    const updateProgress = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const maxScroll = document.documentElement.scrollHeight - window.innerHeight;
        const amount = maxScroll > 0 ? window.scrollY / maxScroll : 0;
        progress.style.transform = `scaleX(${Math.min(1, Math.max(0, amount))})`;
      });
    };

    updateProgress();
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", updateProgress);
      window.removeEventListener("resize", updateProgress);
    };
  }, []);

  return (
    <div className="nx-site">
      <div className="nx-scroll-progress" aria-hidden="true" />
      <header className="nx-header">
        <div className="nx-container nx-header-inner">
          <Link href="/" className="nx-wordmark" aria-label="Cortex Nexus home">
            <span className="nx-mark" aria-hidden="true"><i /><i /><i /><i /></span>
            <span>CORTEX <b>/</b> NEXUS</span>
          </Link>
          <nav className="nx-nav" aria-label="Main navigation">
            <a href="#platform">Platform</a>
            <a href="#intelligence">Intelligence</a>
            <a href="#approach">Approach</a>
          </nav>
          <div className="nx-header-actions">
            <Link className="nx-text-link nx-workspace-link" href="/workspace/cockpit">Open workspace <span>↗</span></Link>
            <Link className="nx-button nx-button-dark nx-button-small" href="/demo">Request a demo <span>↗</span></Link>
          </div>
        </div>
      </header>

      <main>
        <section className="nx-hero">
          <div className="nx-container nx-hero-grid">
            <div className="nx-hero-copy">
              <div className="nx-eyebrow"><span className="nx-eyebrow-rule" /> OPERATIONAL INTELLIGENCE SYSTEM</div>
              <h1>See the whole system.<br /><em>Understand what changes.</em></h1>
              <p className="nx-hero-lede">
                Cortex Nexus turns fragmented operational data into a shared, evidence-linked world state — so teams can understand risk, test decisions, and act with confidence.
              </p>
              <div className="nx-hero-actions">
                <Link href="/demo" className="nx-button nx-button-dark">Explore Nexus <span>↗</span></Link>
                <a href="#platform" className="nx-button nx-button-light">See how it works <span>↓</span></a>
              </div>
              <div className="nx-hero-footnote">
                <span>BUILT FOR COMPLEX OPERATIONS</span>
                <span>GOVERNED. TRACEABLE. HUMAN-DIRECTED.</span>
              </div>
            </div>
            <div className="nx-hero-visual nx-reveal">
              <NetworkField activeStage={activeStage} />
              <div className="nx-visual-note">
                <span className="nx-note-number">01</span>
                <span>One operational picture.<br />Across every dependency.</span>
              </div>
            </div>
          </div>
          <div className="nx-container nx-hero-bottom">
            <span>FROM SOURCE DATA TO DECISION CONTEXT</span>
            <a href="#platform" aria-label="Scroll to platform overview">SCROLL TO EXPLORE <span>↓</span></a>
          </div>
        </section>

        <section className="nx-principles" aria-label="Platform principles">
          <div className="nx-container nx-principles-row">
            <span>ONE CANONICAL WORLD STATE</span><i />
            <span>EVIDENCE AT EVERY LAYER</span><i />
            <span>HUMANS CONTROL EXECUTION</span>
          </div>
        </section>

        <section id="platform" className="nx-story">
          <div className="nx-container">
            <div className="nx-section-heading nx-reveal">
              <div>
                <div className="nx-eyebrow"><span className="nx-eyebrow-rule" /> THE NEXUS METHOD</div>
                <h2>From disconnected records<br /><em>to connected understanding.</em></h2>
              </div>
              <p>Operational intelligence is not another dashboard. It is a consistent model of what exists, how it connects, and what a change could mean.</p>
            </div>

            <div className="nx-story-layout">
              <div className="nx-story-visual">
                <div className="nx-story-visual-sticky">
                  <NetworkField activeStage={activeStage} compact />
                  <div className="nx-stage-readout">
                    <span>ACTIVE LAYER</span>
                    <strong>0{activeStage + 1} <b>/</b> {stages[activeStage].label}</strong>
                  </div>
                </div>
              </div>
              <div className="nx-story-steps">
                {stages.map((stage, index) => (
                  <article
                    className={`nx-story-step nx-reveal ${activeStage === index ? "is-current" : ""}`}
                    data-story-step={index}
                    key={stage.index}
                  >
                    <div className="nx-step-meta"><span>{stage.index}</span><span>{stage.label}</span></div>
                    <h3>{stage.title}</h3>
                    <p>{stage.body}</p>
                    <div className="nx-step-detail">{stage.detail}</div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="intelligence" className="nx-intelligence">
          <div className="nx-container nx-intelligence-grid">
            <div className="nx-intelligence-intro nx-reveal">
              <div className="nx-eyebrow nx-eyebrow-light"><span className="nx-eyebrow-rule" /> REASONING WITH CONTEXT</div>
              <h2>Intelligence that<br /><em>shows its work.</em></h2>
              <p>Every signal, risk, and recommendation should be explainable. Nexus grounds analysis in workspace evidence and keeps the reasoning path visible.</p>
              <Link href="/intelligence" className="nx-light-link">Explore operational intelligence <span>↗</span></Link>
            </div>
            <div className="nx-evidence-card nx-reveal">
              <div className="nx-evidence-card-top">
                <span>DECISION CONTEXT / EXAMPLE</span>
                <span>TRACE 001</span>
              </div>
              <div className="nx-evidence-headline">A change is only useful when its impact is understood.</div>
              <div className="nx-evidence-chain">
                <div className="nx-evidence-item">
                  <span className="nx-evidence-icon">01</span>
                  <div><b>Observed signal</b><small>A source-backed change enters the system.</small></div>
                </div>
                <div className="nx-evidence-connector" />
                <div className="nx-evidence-item">
                  <span className="nx-evidence-icon">02</span>
                  <div><b>Connected impact</b><small>Related entities and dependencies are traced.</small></div>
                </div>
                <div className="nx-evidence-connector" />
                <div className="nx-evidence-item">
                  <span className="nx-evidence-icon">03</span>
                  <div><b>Decision options</b><small>Scenarios are compared before approval.</small></div>
                </div>
              </div>
              <div className="nx-evidence-card-bottom"><span>PROVENANCE FIRST</span><span>HUMAN APPROVAL REQUIRED</span></div>
            </div>
          </div>
        </section>

        <section id="approach" className="nx-capabilities">
          <div className="nx-container">
            <div className="nx-section-heading nx-reveal">
              <div>
                <div className="nx-eyebrow"><span className="nx-eyebrow-rule" /> A SYSTEM, NOT A COLLECTION OF TOOLS</div>
                <h2>Every layer works<br /><em>from the same reality.</em></h2>
              </div>
              <p>One connected foundation for understanding operational state, investigating change, and governing decisions.</p>
            </div>
            <div className="nx-capability-grid">
              <article className="nx-capability nx-reveal">
                <span className="nx-capability-index">01 / MODEL</span>
                <h3>Canonical world state</h3>
                <p>Bring operational entities and relationships into a consistent, versioned model with source lineage.</p>
                <span className="nx-capability-arrow">↗</span>
              </article>
              <article className="nx-capability nx-reveal">
                <span className="nx-capability-index">02 / OBSERVE</span>
                <h3>Signals and risk</h3>
                <p>Understand where conditions are changing and which connected operations may be affected.</p>
                <span className="nx-capability-arrow">↗</span>
              </article>
              <article className="nx-capability nx-reveal">
                <span className="nx-capability-index">03 / SIMULATE</span>
                <h3>Scenario exploration</h3>
                <p>Evaluate counterfactual paths against a known snapshot without mutating operational state.</p>
                <span className="nx-capability-arrow">↗</span>
              </article>
              <article className="nx-capability nx-reveal">
                <span className="nx-capability-index">04 / GOVERN</span>
                <h3>Evidence-led decisions</h3>
                <p>Keep rationale, supporting evidence, policy checks, and human approval in the decision loop.</p>
                <span className="nx-capability-arrow">↗</span>
              </article>
            </div>
          </div>
        </section>

        <section className="nx-closing">
          <div className="nx-container nx-closing-inner nx-reveal">
            <div className="nx-eyebrow nx-eyebrow-light"><span className="nx-eyebrow-rule" /> CORTEX NEXUS</div>
            <h2>Make complexity<br /><em>legible.</em></h2>
            <div className="nx-closing-bottom">
              <p>Start with the operational picture. Move forward with evidence, context, and control.</p>
              <div className="nx-closing-actions">
                <Link href="/demo" className="nx-button nx-button-white">Request a conversation <span>↗</span></Link>
                <Link href="/workspace/cockpit" className="nx-light-link">Open workspace <span>↗</span></Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="nx-footer">
        <div className="nx-container">
          <div className="nx-footer-top">
            <Link href="/" className="nx-wordmark" aria-label="Cortex Nexus home">
              <span className="nx-mark" aria-hidden="true"><i /><i /><i /><i /></span>
              <span>CORTEX <b>/</b> NEXUS</span>
            </Link>
            <p>Operational intelligence for a world that does not stand still.</p>
          </div>
          <div className="nx-footer-bottom">
            <span>© {new Date().getFullYear()} CORTEX. ALL RIGHTS RESERVED.</span>
            <div><Link href="/security">Security</Link><Link href="/contact">Contact</Link><Link href="/workspace/cockpit">Workspace ↗</Link></div>
          </div>
        </div>
      </footer>
    </div>
  );
}
