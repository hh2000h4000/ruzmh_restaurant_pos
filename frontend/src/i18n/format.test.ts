import { describe, expect, it } from "vitest";

import { dateOnly, locale, timeOnly } from "@/i18n";

/**
 * Dates the cashier reads (D-060).
 *
 * The defect this covers was invisible in the source and obvious on the screen:
 * `Intl` under `ar-SA` puts a **U+200F right-to-left mark** between the parts of
 * a date. Inside `.rpos-numeric` — which is `direction: ltr; unicode-bidi:
 * isolate` — those marks re-order the parts, and `2026/08/30` reached the till
 * as **302026/08/**.
 *
 * Nothing about the string looks wrong in a debugger, which is why it is worth
 * a test rather than a careful reading.
 */
const BIDI_MARKS = /[‎‏؜]/;

const AT = "2026-08-30 14:49:00";

describe("a formatted date", () => {
  it("carries no invisible direction marks in Arabic", () => {
    locale.value = "ar";

    expect(dateOnly(AT)).not.toMatch(BIDI_MARKS);
    expect(timeOnly(AT)).not.toMatch(BIDI_MARKS);
  });

  /**
   * `ar-SA` defaults to the Umm al-Qura calendar, so this same date was listed
   * as `17/03/1448 هـ` beside an order number reading `RO-2026-08-01047`. Two
   * calendars on one row, and the invoice uses the Gregorian one.
   */
  it("is the Gregorian date, not the Hijri one", () => {
    locale.value = "ar";

    const formatted = dateOnly(AT);
    expect(formatted).toContain("30");
    expect(formatted).toContain("08");
    expect(formatted).toContain("2026");
    expect(formatted).not.toContain("1448");
  });

  it("is unchanged in English", () => {
    locale.value = "en";

    expect(dateOnly(AT)).not.toMatch(BIDI_MARKS);
    expect(dateOnly(AT)).toContain("2026");
  });
});
