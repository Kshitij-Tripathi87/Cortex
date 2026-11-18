import NexusNav from "@/components/nexus/NexusNav";
import { PlanPausedNotice } from "@/components/auth/PlanPausedNotice";

/**
 * Canonical Cortex Nexus shell. Every `/nexus/*` surface renders inside this
 * frame so the operational navigation (demo spec §3) is identical everywhere
 * and no page carries private chrome.
 */
export default function NexusLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-bg text-ink">
      <div className="mx-auto flex min-h-screen max-w-[1600px]">
        <NexusNav />
        <section className="min-w-0 flex-1">
          {/* Says why task actions are refused once a trial has ended. */}
          <PlanPausedNotice testId="nexus-plan-paused" className="mx-5 mt-4 sm:mx-8" />
          {children}
        </section>
      </div>
    </div>
  );
}
