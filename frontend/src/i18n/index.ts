/**
 * Two languages, no dependency.
 *
 * A library was considered and rejected: the only thing an i18n package would
 * have given us that matters here is Arabic plural selection, and the browser
 * already ships that in `Intl.PluralRules`. What is left — lookup and
 * interpolation — is the thirty lines below, and keeping it here buys one thing
 * a library cannot: **a missing translation is a compile error**, because every
 * locale is typed against the English key set (`messages/ar.ts`).
 *
 * Locale state lives in a module ref rather than a Pinia store so that
 * non-component code can translate too — `api/client.ts` builds error messages
 * a cashier reads.
 *
 * Refs: FR-17.1–FR-17.4, 03_frontend_vue_rules.md, D-032
 */

import { computed, ref } from "vue";

import ar from "./messages/ar";
import en from "./messages/en";

export const LOCALES = ["ar", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export type MessageKey = keyof typeof en.messages;
export type PluralKey = keyof typeof en.plurals;

/** Every form Arabic can need; `other` is the only one a locale must supply. */
export type PluralForms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };

export interface Catalogue {
  messages: Record<MessageKey, string>;
  plurals: Record<PluralKey, PluralForms>;
}

const CATALOGUE: Record<Locale, Catalogue> = { ar, en };

const STORAGE_KEY = "rpos.locale";

/** The default is Arabic: this is a POS for Saudi restaurants, not a port. */
export const locale = ref<Locale>("ar");

export const dir = computed<"rtl" | "ltr">(() => (locale.value === "ar" ? "rtl" : "ltr"));

function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;

  return template.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in params ? String(params[key]) : whole,
  );
}

/** A plain string. */
export function t(key: MessageKey, params?: Record<string, string | number>): string {
  return interpolate(CATALOGUE[locale.value].messages[key], params);
}

/**
 * A counted string.
 *
 * Arabic has six plural categories and uses three of them below ten, so
 * "2 صنف" is wrong where "صنفان" is right. `Intl.PluralRules` picks the
 * category; the catalogue supplies the wording.
 */
export function tn(key: PluralKey, count: number, params?: Record<string, string | number>): string {
  const forms = CATALOGUE[locale.value].plurals[key];
  const category = new Intl.PluralRules(locale.value).select(count);

  return interpolate(forms[category] ?? forms.other, { n: formatNumber(count), ...params });
}

/**
 * Pick the right side of a bilingual pair coming from the database.
 *
 * Masters carry `title` and `title_ar` (`CLAUDE.md` §5.2). Falling back the
 * other way matters: a menu entered only in Arabic must still be readable on an
 * English terminal, and an unnamed button is worse than a wrong-language one.
 */
export function pick(arabic: string | null | undefined, english: string | null | undefined): string {
  return (locale.value === "ar" ? arabic || english : english || arabic) ?? "";
}

/**
 * `-u-nu-latn` is deliberate. `Intl` renders Arabic with Arabic-Indic digits
 * (٤٧٫١٥), but Saudi tills, receipts and ZATCA invoices all use Western ones,
 * and a total that disagrees with the printed invoice is a support call.
 */
function numberLocale(): string {
  return locale.value === "ar" ? "ar-SA-u-nu-latn" : "en-US";
}

/**
 * The same, with the **calendar pinned** — and that is not a detail (D-060).
 *
 * `ar-SA` defaults to the Umm al-Qura calendar, so an order opened on
 * 30/08/2026 was being listed as `17/03/1448 هـ` beside an order number reading
 * `RO-2026-08-01047`. Two calendars on one row, and the bill, the Sales Invoice
 * and the ZATCA submission all use the Gregorian one.
 *
 * A locale default is not a decision. `-nu-latn` was pinned for exactly this
 * reason; the calendar was left to ICU and ICU answered honestly.
 */
function dateLocale(): string {
  return locale.value === "ar" ? "ar-SA-u-nu-latn-ca-gregory" : "en-US";
}

export function formatNumber(value: number, fractionDigits = 0): string {
  return new Intl.NumberFormat(numberLocale(), {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Money is always two decimals (`CLAUDE.md` §4.10). */
export function money(value: number, currency = "SAR"): string {
  // Only the shop's own currency gets a translated name; anything else prints
  // its ISO code rather than inventing a word for it.
  return `${formatNumber(value, 2)} ${currency === "SAR" ? t("currency.sar") : currency}`;
}

/** Wall-clock time for the header. Latin digits, for the reason above. */
export function clockTime(at: Date = new Date()): string {
  return stripBidi(
    new Intl.DateTimeFormat(dateLocale(), {
      hour: "2-digit",
      minute: "2-digit",
    }).format(at),
  );
}

/**
 * A server timestamp, split into the two lines a bill row shows.
 *
 * Frappe sends naive local datetimes ("2026-08-26 16:47:00"), which `Date`
 * reads as UTC once a `T` is added and as local time without one. Replacing the
 * space keeps it local, which is what the shop's clock says.
 */
function parse(value: string): Date {
  return new Date(value.replace(" ", "T"));
}

/**
 * Take out the invisible direction marks `Intl` inserts.
 *
 * Formatting a date under `ar-SA` puts a **U+200F right-to-left mark** between
 * every part — `30‏/08‏/2026`. They are there to make the date read correctly
 * inside an Arabic *sentence*, and every one of these strings is rendered
 * inside `.rpos-numeric`, which is already `direction: ltr; unicode-bidi:
 * isolate`. So the marks are not merely unnecessary there, they are the bug:
 * they re-order the parts inside the isolate and the cashier reads
 * **302026/08/**.
 */
function stripBidi(value: string): string {
  return value.replace(/[‎‏]/g, "");
}

export function dateOnly(value: string): string {
  return stripBidi(
    new Intl.DateTimeFormat(dateLocale(), {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(parse(value)),
  );
}

export function timeOnly(value: string): string {
  return stripBidi(
    new Intl.DateTimeFormat(dateLocale(), {
      hour: "2-digit",
      minute: "2-digit",
    }).format(parse(value)),
  );
}

/**
 * When something started — as briefly as it can be said **truthfully**.
 *
 * The time alone while it is still today's, because that is the whole answer
 * and a date beside it is noise. **The date the moment it is not**, and that
 * half is the point (`D-178`): a clock-in from three days ago drawn as
 * `02:12 م` reads as this afternoon. The till menu did exactly that, under a
 * row whose stated job was to answer *"am I still clocked in from yesterday?"*
 * — and the user read it as a clock-out offered for no reason.
 *
 * One function rather than the three places that each asked it: the till menu,
 * the welcome screen and the manager's roster (`CLAUDE.md` §5.5).
 */
export function sinceWhen(value: string): string {
  const at = parse(value);
  const now = new Date();

  const sameDay =
    at.getFullYear() === now.getFullYear() &&
    at.getMonth() === now.getMonth() &&
    at.getDate() === now.getDate();

  return sameDay ? timeOnly(value) : `${dateOnly(value)} ${timeOnly(value)}`;
}

export function setLocale(next: Locale): void {
  locale.value = next;

  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Private mode or a locked-down kiosk profile. The language still applies
    // for this session; only remembering it fails.
  }

  applyToDocument();
}

/** The `<html>` element owns direction, so CSS logical properties follow it. */
export function applyToDocument(): void {
  document.documentElement.setAttribute("dir", dir.value);
  document.documentElement.setAttribute("lang", locale.value);
}

/**
 * Device choice wins over the user's ERPNext language.
 *
 * A till is shared: whoever configured the terminal picked the language the
 * shop runs in, and the next cashier to sign in should not flip the whole
 * screen because their own profile says otherwise.
 */
export function initLocale(preferred?: string): void {
  const stored = (() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY);
    } catch {
      return null;
    }
  })();

  if (isLocale(stored)) {
    locale.value = stored;
  } else if (isLocale(preferred)) {
    locale.value = preferred;
  }

  applyToDocument();
}
