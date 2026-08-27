/**
 * Tailwind maps brand colours to CSS variables and status colours to literals.
 *
 * That split is the enforcement of FR-15.5. A component writing `bg-primary`
 * follows the theme; a component writing `bg-status-occupied` cannot be themed
 * because there is no variable behind it. The rule is structural rather than a
 * comment someone has to remember.
 *
 * A raw hex anywhere in a component is a bug (03_frontend_vue_rules.md).
 */

/** Brand colour backed by a CSS variable, with opacity-modifier support. */
const themed = (token) => `rgb(var(--rpos-${token}) / <alpha-value>)`;

/** 06_UI_UX_Flow.md §Color System. Fixed on every installation. */
const STATUS = {
  available: "#22C55E",
  occupied: "#EF4444",
  reserved: "#F59E0B",
  cleaning: "#3B82F6",
  inactive: "#9CA3AF",
};

/**
 * Soft accents for chrome — icon tiles, toolbar buttons.
 *
 * Decoration, not meaning: nothing here tells a cashier a table is free or an
 * order is late, so unlike STATUS these carry no operational weight. They live
 * in this file rather than in a component because a raw hex in a component is
 * a lint error (03_frontend_vue_rules.md).
 */
const ACCENT = {
  blue: "#3B82F6",
  teal: "#14B8A6",
  green: "#10B981",
  amber: "#F59E0B",
  violet: "#8B5CF6",
  rose: "#F43F5E",
  slate: "#64748B",
};

/** Order lifecycle, BR-010. Also fixed — cashiers scan by colour. */
const ORDER = {
  draft: "#22C55E",
  active: "#22C55E",
  in_kitchen: "#EF4444",
  pending_payment: "#F59E0B",
  closed: "#9CA3AF",
  cancelled: "#DC2626",
};

export default {
  content: ["./index.html", "./src/**/*.{vue,js,ts}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: themed("primary"),
          contrast: themed("primary-contrast"),
        },
        secondary: {
          DEFAULT: themed("secondary"),
          contrast: themed("secondary-contrast"),
        },
        surface: themed("surface"),
        background: themed("background"),
        content: themed("text"),
        muted: themed("muted"),
        line: themed("border"),

        accent: ACCENT,

        // Never themeable — see FR-15.5.
        status: STATUS,
        order: ORDER,
        danger: "#DC2626",
      },
      borderRadius: {
        rpos: "var(--rpos-radius)",
        "rpos-lg": "calc(var(--rpos-radius) * 1.4)",
      },
      boxShadow: {
        card: "var(--rpos-shadow-card)",
        lift: "var(--rpos-shadow-lift)",
        bar: "var(--rpos-shadow-bar)",
      },
      transitionTimingFunction: {
        // A touch UI feels responsive when motion decelerates quickly rather
        // than easing in — the press should look like it has already happened.
        rpos: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      minWidth: {
        tap: "var(--rpos-tap-target)",
      },
      minHeight: {
        tap: "var(--rpos-tap-target)",
      },
      fontFamily: {
        // System Arabic first; no webfont, because a cashier terminal on a slow
        // connection must not wait for text.
        sans: ["'Segoe UI'", "Tahoma", "'Noto Sans Arabic'", "system-ui", "sans-serif"],
      },
      fontSize: {
        // 06 §Accessibility: nothing below 14px anywhere.
        xs: ["0.875rem", { lineHeight: "1.25rem" }],
      },
    },
  },
  plugins: [],
};
