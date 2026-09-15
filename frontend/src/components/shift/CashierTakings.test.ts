// @vitest-environment jsdom

/**
 * `D-218` — a shared drawer is counted once for everybody on it, and this is
 * where the money is still traced to a name.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CashierTakings from "@/components/shift/CashierTakings.vue";
import { t } from "@/i18n";

const SAEED = { user: "saeed@example.com", name: "سعيد", count: 3, sales: 120, returns: 0 };
const NOURA = { user: "noura@example.com", name: "نورة", count: 1, sales: 40, returns: 15 };

describe("what each cashier took", () => {
  it("lists everybody who rang money into a shared drawer", () => {
    const text = mount(CashierTakings, { props: { rows: [SAEED, NOURA] } }).text();

    expect(text).toContain(t("shift.byCashier"));
    expect(text).toContain("سعيد");
    expect(text).toContain("نورة");
  });

  it("says what somebody gave back beside what they took", () => {
    const text = mount(CashierTakings, { props: { rows: [SAEED, NOURA] } }).text();

    expect(text).toContain(t("shift.cashierReturns", { amount: "15.00" }));
  });

  it("draws nothing for a drawer only its own cashier worked", () => {
    expect(mount(CashierTakings, { props: { rows: [SAEED] } }).text()).toBe("");
  });
});
