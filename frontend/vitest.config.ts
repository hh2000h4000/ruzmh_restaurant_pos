import { resolve } from "node:path";

import { defineConfig } from "vitest/config";

/**
 * Separate from `vite.config.ts` on purpose: that file carries the Frappe
 * publish plugin, and a test run has no business writing into the app's `www`
 * folder.
 *
 * Only logic is tested here — the offline queue's failure classification, which
 * decides whether a cashier's action is retried, abandoned, or replayed twice.
 * Components are verified in a browser (`06_git_testing_rules.md`).
 */
export default defineConfig({
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
  test: {
    environment: "node",
    setupFiles: ["./src/offline/testing/setup.ts"],
    include: ["src/**/*.test.ts"],
  },
});
