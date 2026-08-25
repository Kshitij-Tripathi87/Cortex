"use client";

import React from "react";
import { WorkspaceProvider, useNexusWorkspace } from "@/lib/state/WorkspaceContext";
import { NexusHeader } from "@/components/shell/NexusHeader";
import { NexusSidebar } from "@/components/shell/NexusSidebar";
import { InvalidationBanner } from "@/components/shell/InvalidationBanner";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { WhyExplainerModal } from "@/components/shell/WhyExplainerModal";
import { DemoWalkthroughGuide } from "@/components/shell/DemoWalkthroughGuide";

function WorkspaceShellInner({ children }: { children: React.ReactNode }) {
  const {
    isDecisionValid,
    invalidationReason,
    redeliberate,
    injectStreamEvent,
    setCommandPaletteOpen,
    whyModalOpen,
    whySubject,
    closeWhyModal,
  } = useNexusWorkspace();

  return (
    <div className="min-h-screen bg-bg text-ink flex flex-col font-sans antialiased">
      <NexusHeader
        onInjectEvent={injectStreamEvent}
        onOpenQueryModal={() => setCommandPaletteOpen(true)}
      />
      <CommandPalette />
      <DemoWalkthroughGuide />
      <WhyExplainerModal
        isOpen={whyModalOpen}
        subject={whySubject}
        onClose={closeWhyModal}
      />
      <InvalidationBanner
        isValid={isDecisionValid}
        invalidationReason={invalidationReason}
        onRedeliberate={redeliberate}
      />
      <div className="flex-1 flex overflow-hidden">
        <NexusSidebar />
        <main className="flex-1 overflow-y-auto p-6 bg-bg">
          {children}
        </main>
      </div>
    </div>
  );
}

export default function WorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <WorkspaceProvider>
      <WorkspaceShellInner>{children}</WorkspaceShellInner>
    </WorkspaceProvider>
  );
}
