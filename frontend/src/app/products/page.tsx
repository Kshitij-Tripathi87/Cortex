"use client";

import React from "react";
import { NexusDemo } from "@/components/nexus";
import { PageHeader } from "@/components/PageHeader";

export default function ProductsPage() {
  return (
    <div className="min-h-screen bg-zinc-950">
      <PageHeader
        title="Products"
        description="Operational disruption intelligence and mitigation"
      />

      <main className="px-6 py-8 max-w-7xl mx-auto">
        <NexusDemo reducedMotion={false} />
      </main>
    </div>
  );
}