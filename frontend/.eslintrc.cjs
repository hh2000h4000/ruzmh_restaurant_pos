/* eslint-env node */

/**
 * The colour rule below is the point of this file.
 *
 * `03_frontend_vue_rules.md` says a hex literal inside a component is a bug: it
 * silently opts that element out of the theme (FR-15.4). Status colours do not
 * need one either, because they are Tailwind literals. Making the linter refuse
 * hex means the rule holds without anyone remembering it.
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
  ],
};
