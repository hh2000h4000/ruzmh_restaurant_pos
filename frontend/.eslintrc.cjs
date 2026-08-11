/* eslint-env node */

/**
 * The two restricted-syntax rules below are the point of this file.
 *
 * **Colours.** `03_frontend_vue_rules.md` says a hex literal inside a component
 * is a bug: it silently opts that element out of the theme (FR-15.4). Status
 * colours do not need one either, because they are Tailwind literals.
 *
 * **Arabic literals.** The app ships in two languages (FR-15.6). A string typed
 * straight into a component is invisible to the English catalogue and shows up
 * as Arabic in the middle of an English screen — the kind of defect nobody
 * notices until a customer does. Every user-visible string goes through
 * `t()`, and the linter is what keeps that true.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:vue/vue3-recommended",
    "@vue/eslint-config-typescript",
  ],
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  ignorePatterns: ["dist/", "node_modules/"],
  rules: {
    "no-restricted-syntax": [
      "error",
      {
        selector: "Literal[value=/^#[0-9a-fA-F]{3,8}$/]",
        message:
          "No hardcoded colours. Use a Tailwind token: bg-primary, text-status-occupied.",
      },
      {
        selector: "Literal[value=/[\\u0600-\\u06FF]/]",
        message: "No Arabic literals in components. Add a key to src/i18n/messages and use t().",
      },
    ],
    "vue/multi-word-component-names": "off",
  },
  overrides: [
    {
      // Where colours legitimately live: the token map, the store that writes
      // the CSS variables, and the typed contract.
      files: ["tailwind.config.js", "src/stores/theme.ts", "src/types/*.ts"],
      rules: { "no-restricted-syntax": "off" },
    },
    {
      // The catalogues are where the Arabic belongs.
      files: ["src/i18n/**"],
      rules: { "no-restricted-syntax": "off" },
    },
  ],
};
