// @vitest-environment jsdom

/**
 * What reaches the screen the room can read (`FR-13`, `D-162`).
 *
 * This is the one screen in the app **facing away from the staff**, so the
 * question it is tested on is not only "does it show the bill" but "what can it
 * possibly show". The answer is enforced by what crosses the channel rather
 * than by what the template happens to render: a field never sent cannot be
 * leaked by a later edit to the view.
 */
import { describe, expect, it } from "vitest";

import type { OrderDetail, OrderLine } from "@/api/order";
import { IDLE, NO_BRAND, toDisplayState } from "@/composables/useCustomerDisplay";

function line(extra: Partial<OrderLine> = {}): OrderLine {
  return {
    idx: 1,
    item: "RPOS-BURGER",
    item_name: "برغر",
    qty: 2,
    rate: 25,
    amount: 50,
    status: "pending",
    notes: null,
    modifiers: [],
    production_center: null,
    ...extra,
  } as OrderLine;
}

function bill(extra: Partial<OrderDetail> = {}): OrderDetail {
  return {
    order_name: "RO-2026-09-00042",
    status: "active",
    daily_number: 7,
    subtotal: 50,
    discount_amount: 0,
    promotion_amount: 0,
    promotion_title: "",
    promotion_title_ar: "",
    tax_amount: 6.52,
    total_amount: 50,
    cashier: "cashier@example.com",
    cashier_name: "سعيد الغامدي",
    table: "TBL-4",
    ...extra,
  } as OrderDetail;
}

describe("what the guest's screen is given", () => {
  /**
   * `D-202`. The display window asks the server for nothing, so everything it
   * shows has to arrive over the channel — the name did already, the logo and
   * the manager's message now do.
   */
  it("carries the logo and the manager's message, on a bill and while waiting", () => {
    const brand = { ...NO_BRAND, logo: "/files/logo.png", message: "وجبة الغداء ٤٩" };
    const shown = { logo: "/files/logo.png", message: "وجبة الغداء ٤٩" };

    expect(toDisplayState(bill(), [line()], brand)).toMatchObject(shown);
    expect(toDisplayState(null, [], brand)).toMatchObject({ mode: "idle", ...shown });
  });

  it("says nothing about a brand the till did not send", () => {
    expect(IDLE).toMatchObject({ house: "", logo: null, message: "" });
  });

  /**
   * `D-163`. An offer the guest came in for is the thing they are checking this
   * screen for, and a bare "discount" line does not tell them it was honoured.
   */
  it("names the offer that was applied", () => {
    const state = toDisplayState(
      bill({
        discount_amount: 10,
        promotion_amount: 10,
        promotion_title: "Breakfast offer",
        promotion_title_ar: "عرض الإفطار",
      }),
      [line()],
    );

    expect(state.promotion).toEqual({ title: "عرض الإفطار", amount: 10 });
  });

  it("shows nothing but the house name when there is no bill", () => {
    expect(toDisplayState(null, [], { ...NO_BRAND, house: "فرع الرياض" })).toEqual({
      ...IDLE,
      house: "فرع الرياض",
    });
  });

  /**
   * The display window loads no session — it asks the server for nothing — so
   * its own stores are empty and reading the branch there left the header
   * blank. Found on the first real screen; the name travels with the bill.
   */
  it("carries the restaurant's name, because the other window cannot look it up", () => {
    expect(toDisplayState(bill(), [line()], { ...NO_BRAND, house: "فرع الرياض" }).house).toBe(
      "فرع الرياض",
    );
  });

  /**
   * VAT is inclusive here (`D-091`), so `subtotal` already contains the tax.
   * Printed beside the tax and the total it gave the guest `60.00 + 7.83 =
   * 60.00` — true, and unreadable as anything but a mistake. Derived from the
   * total, the three figures add up on the screen.
   */
  it("gives the guest three figures that add up", () => {
    const state = toDisplayState(bill({ total_amount: 60, tax_amount: 7.83 }), [line()]);

    expect(state.beforeTax).toBeCloseTo(52.17, 2);
    expect(state.beforeTax + state.tax).toBeCloseTo(state.total, 2);
  });

  it("carries the lines, the options and the totals", () => {
    const state = toDisplayState(bill(), [
      line({
        modifiers: [
          { group: "G", option: "No onion", option_ar: "بدون بصل", amount: 0 },
        ] as OrderLine["modifiers"],
      }),
    ]);

    expect(state.mode).toBe("order");
    expect(state.lines).toEqual([
      { name: "برغر", qty: 2, amount: 50, options: ["بدون بصل"] },
    ]);
    expect(state.total).toBe(50);
    expect(state.tax).toBe(6.52);
  });

  /**
   * **The point of the whole shape.** The room reads this screen: a cashier's
   * name, a document id or a terminal on it is a leak, and the way to be sure
   * is that they never leave the till.
   */
  it("carries nothing that identifies a person or a document", () => {
    const sent = JSON.stringify(toDisplayState(bill(), [line()]));

    expect(sent).not.toContain("RO-2026-09-00042");
    expect(sent).not.toContain("cashier@example.com");
    expect(sent).not.toContain("سعيد الغامدي");
    expect(sent).not.toContain("TBL-4");
  });

  /**
   * A line taken off is not part of what is owed. Leaving it on the guest's
   * screen is how somebody queries a total that is already right.
   */
  it("leaves a voided line off", () => {
    const state = toDisplayState(bill(), [
      line({ item_name: "برغر" }),
      line({ idx: 2, item_name: "بيبسي", status: "void" }),
    ]);

    expect(state.lines.map((row) => row.name)).toEqual(["برغر"]);
  });

  /**
   * `FR-2.10` — and this is the number's right home. It came off the orders
   * list because that list mixes days and the number restarts daily, so two
   * rows could read the same (`D-159`). Here there is one bill.
   */
  it("carries the number the guest will be called by", () => {
    expect(toDisplayState(bill(), [line()]).number).toBe(7);
  });

  it("has no number to show when the branch does not number bills", () => {
    expect(toDisplayState(bill({ daily_number: 0 }), [line()]).number).toBeNull();
  });
});
