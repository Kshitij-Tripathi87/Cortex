"use client";

import { usePathname } from "next/navigation";
import { Navigation } from "@/components/Navigation";
import { WorkspaceSelector } from "@/components/WorkspaceSelector";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen">
      <Navigation currentPath={pathname} />
      <div className="flex-1 flex flex-col">
        <header className="h-14 border-b border-gray-200 bg-white px-6 flex items-center justify-between sticky top-0 z-10">
          <div />
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-400">Workspace:</span>
            <WorkspaceSelector />
          </div>
        </header>
        <main className="flex-1 p-6 bg-gray-50 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
