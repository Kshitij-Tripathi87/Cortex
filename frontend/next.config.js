/** @type {import('next').NextConfig} */
const apiOrigin = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const apiBase = (
  process.env.NEXT_PUBLIC_API_BASE_URL || `${apiOrigin}/api/v1`
).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  env: {
    // Public variables are inlined at build time. Production images must use
    // the externally reachable API origin, never browser-local localhost.
    NEXT_PUBLIC_API_URL: apiOrigin,
    NEXT_PUBLIC_API_BASE_URL: apiBase,
  },
}

module.exports = nextConfig