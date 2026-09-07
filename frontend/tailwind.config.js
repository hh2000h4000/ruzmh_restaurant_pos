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
 * Soft accents for chrome.
 *
 * Decoration, not meaning: nothing here tells a cashier a table is free or an
 * order is late, so unlike STATUS these carry no operational weight. They live
 * in this file rather than in a component because a raw hex in a component is
 * a lint error (03_frontend_vue_rules.md).
 *
 * **One entry, because one is used.** Seven shipped here for "icon tiles and
 * toolbar buttons" and not a single component ever referenced any of them —
 * dead paint that a reader has to decide about every time they open this file
 * (`CLAUDE.md` §5.5). They are in the history if a use appears.
 */
const ACCENT = {
  // The figure that is still owed. Warmer and darker than `status.reserved`,
  // which is a *table* state and must not drift to follow a house style.
  gold: "#B8791F",
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
        /*
         * The step between the ink and the grey (`D-159`).
         *
         * A row has three levels of voice, not two: the value, the thing beside
         * it that is still content — a status, an order type — and the caption
         * that names them. With only `muted` under `content`, the second and
         * third were drawn the same and the row read as one flat block.
         */
        subtle: themed("subtle"),
        // `line` edges a card; `line-strong` edges a control you press.
        line: {
          DEFAULT: themed("border"),
          strong: themed("border-strong"),
        },

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
        // Brand-tinted, for the single filled button a screen ends on.
        primary: "var(--rpos-shadow-primary)",
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
      // A control sized *exactly* to the minimum, for a strip whose whole job
      // is to stay out of the way — the nav bar under the menu (06 Screen 3).
      height: {
        tap: "var(--rpos-tap-target)",
      },
      fontFamily: {
        // IBM Plex Sans Arabic is the house face; Cairo and Tajawal follow for
        // terminals that already carry one of those.
        // Nothing is fetched from a CDN: this app has to start during an
        // outage, and a webfont over a dead link is a screen with no text on
        // it. Self-hosting the files is the way to guarantee them.
        sans: [
          "'IBM Plex Sans Arabic'",
          "Cairo",
          "Tajawal",
          "'Segoe UI'",
          "Tahoma",
          "'Noto Sans Arabic'",
          "system-ui",
          "sans-serif",
        ],
        // Every figure on a till is set in this: a bill read aloud to a
        // customer is compared digit by digit against a printed slip, and
        // proportional numerals make 1 and 7 argue at arm's length.
        mono: [
          "'IBM Plex Mono'",
          "'SF Mono'",
          "'Cascadia Mono'",
          "Consolas",
          "'Liberation Mono'",
          "monospace",
        ],
      },
      fontSize: {
        /*
         * **14px is the floor for anything a cashier *reads*** (06
         * §Accessibility). The two sizes under it are named rather than written
         * as arbitrary values so the exception cannot spread by accident: a
         * component asking for `text-label` is saying "this is a caption", and
         * a reviewer can grep for every place that claim was made (`D-159`).
         */
        xs: ["0.875rem", { lineHeight: "1.25rem" }],
        /**
         * 11.5px — the small grey word **under** a value: "المبلغ", "صنف",
         * "الكاشير". Read once while learning the screen and never again, which
         * is why it may be quiet. Never for a value, a status or a name.
         */
        label: ["0.719rem", { lineHeight: "1rem" }],
        /**
         * 12px — a date, a time, a reference. **Mono digits only.** Arabic
         * script carries more fine detail than Latin and needs the extra size
         * for the same legibility, so a word never uses this.
         */
        meta: ["0.75rem", { lineHeight: "1.05rem" }],
      },
    },
  },
  plugins: [],
};
