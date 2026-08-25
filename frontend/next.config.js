/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    // Raw backend host used by src/lib/api.ts (full paths are layered in code).
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    // Convenience full-base form for components that build URLs by hand
    // (e.g. the upload form, which posts multipart directly).
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1",
  },
}

module.exports = nextConfig