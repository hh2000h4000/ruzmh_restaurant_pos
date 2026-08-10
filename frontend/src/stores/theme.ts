import { defineStore } from "pinia";
import { ref } from "vue";

import type { ThemeTokens } from "@/types/session";

/**
 * Applies the brand tokens from `load_pos_session` to the document.
 *
 * The only place that writes colour into the DOM. Components read colours
 * through Tailwind classes that resolve to these variables, so a theme change
 * is one `setProperty` call and never a component change (FR-15.4).
 *
 * Status colours are absent on purpose — they are Tailwind literals with no
 * variable to write to (FR-15.5).
 */

/** `#1D4ED8` -> `29 78 216`, the channel form Tailwind's opacity syntax needs. */
export function hexToChannels(hex: string): string | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return null;

  let value = match[1];
  if (value.length === 3) {
    value = value
      .split("")
      .map((char) => char + char)
      .join("");
  }

  const int = Number.parseInt(value, 16);
  return `${(int >> 16) & 255} ${(int >> 8) & 255} ${int & 255}`;
}

/** Relative luminance, per WCAG 2.1. */
function luminance(channels: string): number {
  const [r, g, b] = channels.split(" ").map((n) => {
    const c = Number(n) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast ratio between two channel strings. */
export function contrastRatio(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

const TOKEN_ORDER: (keyof ThemeTokens)[] = [
  "primary",
  "primary_contrast",
  "secondary",
  "secondary_contrast",
  "surface",
  "background",
  "text",
];

export const useThemeStore = defineStore("theme", () => {
  const applied = ref<Partial<ThemeTokens>>({});
  const warnings = ref<string[]>([]);

  function apply(theme: Partial<ThemeTokens> | null | undefined): void {
    if (!theme) return;

    const root = document.documentElement;

    for (const token of TOKEN_ORDER) {
      const value = theme[token];
      if (typeof value !== "string") continue;

      const channels = hexToChannels(value);
      if (!channels) {
        warnings.value.push(`Ignored malformed colour for ${token}: ${value}`);
        continue;
      }

      root.style.setProperty(`--rpos-${token.replace(/_/g, "-")}`, channels);
      applied.value[token] = value;
    }

    checkContrast();
  }

  /**
   * The backend rejects unreadable combinations before they are saved
   * (FR-15.3). This is a second, local check so a theme that arrived from an
   * older server still gets flagged rather than shipping an unreadable till.
   */
  function checkContrast(): void {
    const root = getComputedStyle(document.documentElement);
    const pairs: [keyof ThemeTokens, string, string][] = [
      ["primary", "--rpos-primary", "--rpos-primary-contrast"],
      ["secondary", "--rpos-secondary", "--rpos-secondary-contrast"],
      ["text", "--rpos-background", "--rpos-text"],
    ];

    for (const [token, backgroundVar, foregroundVar] of pairs) {
      const background = root.getPropertyValue(backgroundVar).trim();
      const foreground = root.getPropertyValue(foregroundVar).trim();
      if (!background || !foreground) continue;

      if (contrastRatio(background, foreground) < 4.5) {
        warnings.value.push(`Low contrast on ${token} — below the 4.5:1 minimum`);
      }
    }
  }

  function reset(): void {
    const root = document.documentElement;
    for (const token of TOKEN_ORDER) {
      root.style.removeProperty(`--rpos-${token.replace(/_/g, "-")}`);
    }
    applied.value = {};
    warnings.value = [];
  }

  return { applied, warnings, apply, reset };
});
