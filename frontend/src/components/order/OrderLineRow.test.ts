// @vitest-environment jsdom

/**
 * The offer, drawn on the dish it came off (`D-166`).
 *
 * The bill's totals block names the promotion and gives its figure. On a bill
 * where the offer covers three items out of seven that still does not say
 * *which* — and that is the question the guest asks while pointing at one of
 * them. Toast puts the discount as a line beneath the item it discounted and
 * Foodics writes the offer's name under the dish.
 *
 * No backend test can see whether the line was drawn: the server can allocate
 * the shares perfectly and the row render nothing, and the suite would be green
 * either way (`D-130`).
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { OrderLine } from "@/api/order";
import OrderLineRow from "@/components/order/OrderLineRow.vue";

function row(line: Partial<OrderLine>, promotionLabel = "عرض الإفطار") {
  return mount(OrderLineRow, {
    props: {
      promotionLabel,
      line: {
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
        ...line,
      } as OrderLine,
    },
    global: { stubs: { AppIcon: true } },
  });
}

describe("saying which dish the offer came off", () => {
  it("names the offer and what it took off this line", () => {
    const text = row({ promotion_amount: 12.5 }).text();

    expect(text).toContain("عرض الإفطار");
    expect(text).toContain("12.50");
  });

  /**
   * The case the whole thing exists for: a bill holding both. A line the offer
   * never reached must stay bare, or the mark says nothing at all.
   */
  it("leaves a line the offer never reached bare", () => {
    const text = row({ promotion_amount: 0 }).text();

    expect(text).not.toContain("عرض الإفطار");
  });

  /**
   * A share with no name would draw a green amount the cashier cannot explain —
   * and that is what an offline bill carries, where the engine never ran.
   */
  it("draws nothing when there is an amount but no name", () => {
    const text = row({ promotion_amount: 12.5 }, "").text();

    expect(text).not.toContain("12.50");
  });
});
