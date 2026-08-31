import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
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
 * The CSRF token, rendered per session by Jinja.
 *
 * This only works because the page is declared `no_cache` in
 * `restaurant_pos/www/restaurant-pos.py`. Frappe caches a rendered www page
 * under its path alone, with no user in the key, so a cached page would hand
 * every terminal the first visitor's token. Do not remove that file.
 *
 * `or ""` guards a smaller version of the same mistake: an anonymous session
 * has no token and Jinja would otherwise render the literal string "None",
 * which looks like a valid token to any truthiness check.
 */
/**
 * The manifest turns the tab into an installed terminal (D-079).
 *
 * Without it the browser never offers **Install**, and the till stays a tab —
 * whose storage the browser is free to evict when the disk fills, taking the
 * cached app *and* any offline sale still in the queue with it. Installed apps
 * are the ones browsers keep.
 *
 * It lives in `www/` rather than the build output because it is content, not
 * code: a restaurant replaces the icon and the name, and rebuilding the
 * frontend to change a logo would be absurd.
 */
const HEAD_INJECTION = [
  '  <script>window.csrf_token = "{{ frappe.session.csrf_token or "" }}";</script>',
  '  <link rel="manifest" href="/rpos-manifest.json">',
  '  <link rel="icon" href="/rpos-icon.svg" type="image/svg+xml">',
  '  <meta name="theme-color" content="#2563eb">',
  "  ",
].join("\n");

/** Hand-written; the build only fills in what it alone knows (D-078). */
const SW_TEMPLATE = resolve(__dirname, "sw-template.js");

/**
 * The worker is written to `www/sw.js`, which Frappe serves at **`/sw.js`**.
 *
 * It cannot live under `/restaurant-pos/`: `hooks.website_route_rules` sends
 * every path there to the SPA page, so the request would come back as HTML. And
 * it cannot live under `/assets/`, because a worker's scope is its own
 * directory and `/assets/...` cannot control `/restaurant-pos`.
 */
function publishToFrappe(): Plugin {
  /** Every chunk Rollup emitted, captured where the list actually exists. */
  let emitted: string[] = [];

  return {
    name: "rpos-publish-to-frappe",
    apply: "build",

    writeBundle(_options, bundle) {
      // **Not read out of index.html.** That page names only the entry chunk;
      // every view is a lazy import, so a precache built from it would leave a
      // terminal that reloads offline with a shell and no screens. The bundle
      // is the only place that knows all of them.
      //
      // Source maps are left out on purpose: a till has no debugger open and
      // they are larger than the code.
      emitted = Object.keys(bundle).filter((file) => /\.(js|css)$/.test(file));
    },

    closeBundle() {
      const html = readFileSync(resolve(OUT_DIR, "index.html"), "utf-8");

      if (!html.includes("</head>")) {
        throw new Error("Built index.html has no </head>; the CSRF token cannot be injected.");
      }

      mkdirSync(resolve(WWW_PAGE, ".."), { recursive: true });
      writeFileSync(WWW_PAGE, html.replace("</head>", `${HEAD_INJECTION}</head>`), "utf-8");

      writeFileSync(resolve(WWW_PAGE, "../sw.js"), buildServiceWorker(emitted), "utf-8");
    },
  };
}

/** Fill the worker in with this build's asset URLs (D-078). */
function buildServiceWorker(files: string[]): string {
  if (!files.length) {
    throw new Error("The bundle emitted no js or css; the service worker would cache nothing.");
  }

  // The manifest and the icon are served from `www/`, not from the bundle, so
  // the build does not know them — but an installed terminal that opens offline
  // should still have its own name and mark (D-079). Both are tiny.
  const urls = [
    ...files.map((file) => ASSET_BASE + file),
    "/rpos-manifest.json",
    "/rpos-icon.svg",
  ].sort();

  return (
    readFileSync(SW_TEMPLATE, "utf-8")
      .replace('["__PRECACHE__"]', JSON.stringify(urls, null, 2))
      // Global, because the placeholder is named in the file's own comment
      // first — a plain `replace` renamed the documentation and left the code.
      //
      // The id is derived from the URLs, which carry content hashes: a build
      // that changed nothing must not evict a terminal's cache for no reason.
      .replace(/__BUILD__/g, createHash("sha1").update(urls.join("|")).digest("hex").slice(0, 12))
  );
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
