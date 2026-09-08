import { describe, expect, it } from "vitest";

import { reductionsOn } from "./order";

/**
 * `D-163`. The server folds the promotion and the manual discount into one
 * `discount_amount` so the tax is worked out once — right, and it leaves a
 * single figure standing for two different things (`BR-032`).
 *
 * The till, the payment screen and the guest's screen all have to undo that
 * fold, so it is undone here once. This file is why that is safe.
 */
function bill(extra: Partial<Parameters<typeof reductionsOn>[0]> = {}) {
  return {
    discount_amount: 0,
    promotion_amount: 0,
    promotion_title: "",
    promotion_title_ar: "",
    ...extra,
  } as NonNullable<Parameters<typeof reductionsOn>[0]>;
}

describe("telling a promotion from a discount", () => {
  it("names the promotion and leaves the discount at nothing", () => {
    const { promotion, discount } = reductionsOn(
      bill({
        discount_amount: 10,
        promotion_amount: 10,
        promotion_title: "Breakfast offer",
        promotion_title_ar: "عرض الإفطار",
      }),
    );

    expect(promotion).toEqual({ title: "عرض الإفطار", amount: 10 });
    expect(discount).toBe(0);
  });

  /**
   * The case that matters at the payment screen: **the manager approving a
   * discount must be shown the discount**, not the discount plus an offer that
   * was applied before anybody asked.
   */
  it("separates the two when a person discounted on top of an offer", () => {
    const { promotion, discount } = reductionsOn(
      bill({
        discount_amount: 15,
        promotion_amount: 10,
        promotion_title: "Breakfast offer",
        promotion_title_ar: "عرض الإفطار",
      }),
    );

    expect(promotion?.amount).toBe(10);
    expect(discount).toBe(5);
  });

  it("shows no offer on a bill that had none", () => {
    expect(reductionsOn(bill({ discount_amount: 5 }))).toEqual({
      promotion: null,
      discount: 5,
    });
  });

  /**
   * A bill built offline carries an amount but no name — the engine runs on the
   * server. The line is not drawn, and **the amount stays inside the discount**
   * rather than disappearing from the bill: a total has to keep adding up even
   * when a screen cannot label one of its parts.
   */
  it("keeps an unnamed amount in the discount rather than losing it", () => {
    const { promotion, discount } = reductionsOn(
      bill({ discount_amount: 10, promotion_amount: 10 }),
    );

    expect(promotion).toBeNull();
    expect(discount).toBe(10);
  });

  it("has nothing to report with no bill at all", () => {
    expect(reductionsOn(null)).toEqual({ promotion: null, discount: 0 });
  });
});
