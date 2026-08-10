import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import vue from "@vitejs/plugin-vue";
import { defineConfig, type Plugin } from "vite";

/** Where Frappe serves this app's static files from. */
const ASSET_BASE = "/assets/restaurant_pos/frontend/";

/** Build output, inside the Frappe app's public folder. */
const OUT_DIR = resolve(__dirname, "../restaurant_pos/public/frontend");

/** The Jinja page Frappe renders at /restaurant-pos. */
const WWW_PAGE = resolve(__dirname, "../restaurant_pos/www/restaurant-pos.html");

/**
 * Publish the built index.html as a Frappe website page.
 *
 * Vite hashes asset filenames, so the page that loads them has to be generated
 * from the build rather than written by hand. Frappe renders www/*.html through
 * Jinja, so the braces Vue may emit are escaped with `raw`.
 */
function publishToFrappe(): Plugin {
  return {
    name: "rpos-publish-to-frappe",
    apply: "build",
    closeBundle() {
      const html = readFileSync(resolve(OUT_DIR, "index.html"), "utf-8");

      mkdirSync(resolve(WWW_PAGE, ".."), { recursive: true });
      writeFileSync(
        WWW_PAGE,
        [
          "{% raw %}",
          html,
          "{% endraw %}",
          "",
        ].join("\n"),
        "utf-8",
      );

      // The service worker must be served from the app root, not /assets,
      // or its scope cannot cover the whole SPA.
      try {
        copyFileSync(resolve(OUT_DIR, "sw.js"), resolve(WWW_PAGE, "../sw.js"));
      } catch {
        // No service worker yet — Workbox lands with the offline queue.
      }
    },
  };
}

export default defineConfig({
  base: ASSET_BASE,
  plugins: [vue(), publishToFrappe()],
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    target: "es2020",
    sourcemap: true,
    rollupOptions: {
      output: {
        // A cashier on restaurant Wi-Fi should not re-download Vue because a
        // view changed.
        manualChunks: {
          vendor: ["vue", "vue-router", "pinia"],
        },
      },
    },
  },
  server: {
    port: 8080,
    proxy: {
      // `yarn dev` talks to the bench on :8000 so the SPA can be developed
      // against real data without a build step.
      "^/(api|assets|files|private)": {
        target: "http://rpos.localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
