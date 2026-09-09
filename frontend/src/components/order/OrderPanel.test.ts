// @vitest-environment jsdom

/**
 * The wiring between the bill and its lines (`D-166`).
 *
 * `OrderLineRow` draws the offer's name and `OrderPanel` is the only thing that
 * knows it — the promotion belongs to the **bill**, not the line. Everything on
 * both sides can be right while the name never crosses between them, and every
 * other test in the suite stays green: the row's own tests hand it the prop
 * directly, and the server's tests cannot see a screen at all.
 *
 * That gap was found by mutation rather than by review — breaking the panel's
 * binding left 157 tests passing and no line marked on any bill.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { OrderDetail, OrderLine } from "@/api/order";
import OrderPanel from "@/components/order/OrderPanel.vue";

vi.mock("@/stores/session", () => ({
  useSessionStore: () => ({
    can: () => true,
    profile: null,
    data: null,
    orderTypes: [],
  }),
}));

function line(extra: Partial<OrderLine> = {}): OrderLine {
  return {
    idx: 1,
    item: "RPOS-BURGER",
    item_name: "برغر",
    qty: 1,
    rate: 25,
    amount: 25,
    status: "pending",
    notes: null,
    modifiers: [],
    production_center: null,
    promotion_amount: 0,
    ...extra,
  } as OrderLine;
}

function bill(extra: Partial<OrderDetail> = {}): OrderDetail {
  return {
    order_name: "RO-2026-09-00001",
    status: "active",
    daily_number: 7,
    subtotal: 50,
    discount_amount: 5,
    promotion_amount: 5,
    promotion_title: "Breakfast offer",
    promotion_title_ar: "عرض الإفطار",
    tax_amount: 6,
    total_amount: 45,
    item_count: 2,
    order_type: "OT-01",
    table: null,
    table_number: null,
    tables: [],
    section: null,
    ...extra,
  } as OrderDetail;
}

function panel(order: OrderDetail | null, lines: OrderLine[]) {
  return mount(OrderPanel, {
    props: { order, lines },
    global: { stubs: { AppIcon: true, teleport: true } },
  });
}

describe("carrying the offer's name down to the dish", () => {
  it("marks the line the offer reached, by name", () => {
    const text = panel(bill(), [line({ promotion_amount: 5 })]).text();

    expect(text).toContain("عرض الإفطار");
  });

  /**
   * The case the whole feature is for: one bill, one offer, and an item it
   * never touched. The totals block says "-5.00" either way; only the line can
   * say which dish.
   */
  it("leaves the line the offer never reached bare", () => {
    const wrapper = panel(bill(), [
      line({ idx: 1, promotion_amount: 5 }),
      line({ idx: 2, item_name: "قهوة", promotion_amount: 0 }),
    ]);

    const marks = wrapper.findAll("li").filter((row) => row.text().includes("عرض الإفطار"));

    expect(marks).toHaveLength(1);
    expect(marks[0].text()).toContain("برغر");
  });
});
