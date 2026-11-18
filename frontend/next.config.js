/** @type {import('next').NextConfig} */
const apiOrigin = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const apiBase = (
  process.env.NEXT_PUBLIC_API_BASE_URL || `${apiOrigin}/api/v1`
).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  // Emit .next/standalone for the production Docker image
  // (frontend/Dockerfile copies /app/.next/standalone and runs server.js).
  // `next start` (used by e2e) keeps working — standalone is additive.
  output: "standalone",
  env: {
    // Public variables are inlined at build time. Production images must use
    // the externally reachable API origin, never browser-local localhost.
    NEXT_PUBLIC_API_URL: apiOrigin,
    NEXT_PUBLIC_API_BASE_URL: apiBase,
  },
  // The old /workspace demo area was removed. Its screens showed invented
  // figures; the working product lives under /nexus. Old links and bookmarks
  // are sent to the working cockpit, and the one real page it contained (the
  // review of a single agent task) to its new address. Query strings such as
  // ?task_id=… are carried over by Next. Temporary (307) on purpose, so a
  // browser never caches the hop for good.
  async redirects() {
    return [
      {
        source: "/workspace/agents/decision-room",
        destination: "/nexus/decision-room/task",
        permanent: false,
      },
      { source: "/workspace", destination: "/nexus/cockpit", permanent: false },
      { source: "/workspace/:path*", destination: "/nexus/cockpit", permanent: false },
    ];
  },
}

module.exports = nextConfig