import { resolve } from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

/**
 * Separate from `vite.config.ts` on purpose: that file carries the Frappe
 * publish plugin, and a test run has no business writing into the app's `www`
 * folder.
 *
 * Two kinds of test live here.
 *
 * **Logic** — money, the offline queue's failure classification, the router's
 * guard — runs in `node`, which is the default because it is the faster
 * environment and most of the suite needs nothing else.
 *
 * **Components** opt into a DOM per file with a `@vitest-environment jsdom`
 * docblock. They exist because of a run of defects nothing here could have
 * caught: the server refused something the screen had left tappable, and the
 * only witness was the user working a till (`D-125`, `D-126`, `D-127`). A
 * component test asks the one question those defects failed — *is the control
 * the cashier can reach the control the server will accept* — and it asks it
 * without a browser, a bench, or a demo site.
 *
 * They are **not** here to assert how the screen looks. A test that pins a
 * class name breaks on every redesign and protects nothing; every assertion in
 * them is about a control being reachable or not.
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
  test: {
    environment: "node",
    setupFiles: ["./src/offline/testing/setup.ts"],
    include: ["src/**/*.test.ts"],
  },
});
