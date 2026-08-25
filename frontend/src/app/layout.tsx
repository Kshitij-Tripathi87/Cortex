import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cortex Nexus — Autonomous Decision Intelligence & Operational Digital Twin",
  description: "Enterprise operational intelligence platform for supply chains, graph analytics, and multi-agent model orchestration.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-bg text-ink min-h-screen antialiased font-sans">
        {children}
      </body>
    </html>
  );
}
