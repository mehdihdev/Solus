import { defineConfig } from "vitest/config";

/**
 * Workspace-root Vitest config.
 *
 * The Solus quality hooks (H9 PostToolUse, H10 Stop gate) invoke
 * `npx --no-install vitest` from the git root, so vitest must be resolvable and
 * configured here. Each package owns its real config; this file just registers
 * them as projects, so running a single test file from the root applies that
 * package's environment (jsdom), aliases, and setup.
 */
export default defineConfig({
  test: {
    projects: [
      "apps/*/vitest.config.ts",
      "packages/shared-types/vitest.config.ts",
    ],
  },
});
