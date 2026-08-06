import { defineConfig } from "vitest/config";

/**
 * Vitest for the shared contracts (LANE 0).
 *
 * Node environment, no setup files, no DOM: these are types, pure helpers and
 * fixtures. A contract that needed a browser to be tested would be the wrong
 * shape for six lanes to build against.
 */
export default defineConfig({
  test: {
    name: "shared-types",
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
