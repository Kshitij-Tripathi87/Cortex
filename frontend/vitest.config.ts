import path from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // Mirror the tsconfig path alias so src modules importing "@/..." resolve.
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    testTimeout: 10000,
    reporters: ["basic"],
  },
});
