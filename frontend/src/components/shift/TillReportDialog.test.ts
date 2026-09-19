// @vitest-environment jsdom

/**
 * Reading the X report costs no paper (`D-237`).
 *
 * The figures were printable and nothing else, so checking what the drawer
 * should hold meant a receipt — and the user's customers print it twice around
 * every break to compare. This screen shows them, and keeps printing as a
 * button beside the figures rather than instead of them.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShiftReport } from "@/api/shift";
import TillReportDialog from "@/components/shift/TillReportDialog.vue";
import { useShiftStore } from "@/stores/shift";

const REPORT = {
  shift: "SHF-0001",
  branch: "Riyadh",
  status: "open",
  orders: { total: 9, closed: 8, cancelled: 1, still_open: 0 },
  by_order_type: [{ order_type: "OT-007", title_ar: "محلي", count: 8, sales: 420 }],
  by_cashier: [{ user: "a@b.c", name: "نورة", count: 8, sales: 420, returns: 0 }],
  by_method: [
    { method: "Cash", kind: "till", sales: 300, refunds: 0, opening: 0, expected: 300 },
    { method: "HungerStation", kind: "credit", sales: 120, refunds: 0, opening: 0, expected: 0 },
  ],
  voids: 2,
  sales: 420,
  discounts: 15,
  till_expected: 300,
  credit_total: 120,
} as unknown as ShiftReport;

function dialog() {
  return mount(TillReportDialog, {
    props: { open: true },
    global: { stubs: { AppIcon: true, teleport: true } },
  });
}

describe("the X report on screen", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows the drawer's figures without touching the cash drawer", async () => {
    const shift = useShiftStore();
    const summary = vi.spyOn(shift, "tillSummary").mockResolvedValue(REPORT);

    const view = dialog();
    await flushPromises();

    // `false`: only the closing screen, where somebody is counting, pops it.
    expect(summary).toHaveBeenCalledWith();
    expect(view.text()).toContain("300");
    expect(view.text()).toContain("Cash");
    expect(view.text()).toContain("محلي");
  });

  it("prints the same report on demand", async () => {
    const shift = useShiftStore();
    vi.spyOn(shift, "tillSummary").mockResolvedValue(REPORT);
    const print = vi.spyOn(shift, "printTillReport").mockResolvedValue(true);

    const view = dialog();
    await flushPromises();
    await view.findAll("button").at(-1)?.trigger("click");
    await flushPromises();

    expect(print).toHaveBeenCalled();
  });
});
