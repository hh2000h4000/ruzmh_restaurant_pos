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
 * from the build rather than written by hand.
 *
 * The page **must** go through Jinja, because that is what injects the CSRF
 * token. Without it every POST is rejected with a bare 400 and the app looks
 * broken while every GET keeps working — which is exactly how this surfaced.
 * Vite's index.html is static, so there is nothing here Jinja could misread.
 */
/**
 * Two lines go into <head>, and both are load-bearing.
 *
 * `<!-- no-cache -->` is Frappe's own opt-out, and this page cannot live
 * without it. A rendered www page is cached in redis under its path alone —
 * no user and no session in the key (`website/utils.py:cache_html`). A page
 * carrying a per-session CSRF token would therefore be rendered once and
 * handed to everyone after that: whoever loads it first decides every other
 * cashier's token, and if that first visitor was signed out the token is empty
 * and no till can write anything.
 *
 * `or ""` guards the same class of mistake in miniature: an anonymous session
 * has no token and Jinja would otherwise render the literal string "None",
 * which looks like a valid token to any truthiness check.
 */
const HEAD_INJECTION = [
  "  <!-- no-cache -->",
  '  <script>window.csrf_token = "{{ frappe.session.csrf_token or "" }}";</script>',
  "  ",
].join("\n");

function publishToFrappe(): Plugin {
  return {
    name: "rpos-publish-to-frappe",
    apply: "build",
    closeBundle() {
      const html = readFileSync(resolve(OUT_DIR, "index.html"), "utf-8");

      if (!html.includes("</head>")) {
        throw new Error("Built index.html has no </head>; the CSRF token cannot be injected.");
      }

      mkdirSync(resolve(WWW_PAGE, ".."), { recursive: true });
      writeFileSync(WWW_PAGE, html.replace("</head>", `${HEAD_INJECTION}</head>`), "utf-8");

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
