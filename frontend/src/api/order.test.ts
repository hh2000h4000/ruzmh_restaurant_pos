import { describe, expect, it } from "vitest";

import { reductionsOn, whatOpens, type OpenOrder } from "./order";

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

describe("a bill carrying more than one offer", () => {
  /**
   * `D-182` — several offers may land on one bill, on different lines
   * (`BR-034`). A row naming one of them while the figure covers both is the
   * same unanswerable report as no name at all: the guest points at a dish the
   * named offer never touched.
   */
  it("names every offer that landed", () => {
    const { promotion } = reductionsOn(
      bill({
        discount_amount: 13,
        promotion_amount: 13,
        promotion_title: "Grills",
        promotion_title_ar: "الشوايات",
        promotions: [
          { name: "P1", title: "Grills", title_ar: "الشوايات", amount: 8 },
          { name: "P2", title: "Drinks", title_ar: "المشروبات", amount: 5 },
        ],
      }),
    );

    expect(promotion).toEqual({ title: "الشوايات، المشروبات", amount: 13 });
  });

  it("keeps the single name when only one landed", () => {
    const { promotion } = reductionsOn(
      bill({
        discount_amount: 8,
        promotion_amount: 8,
        promotion_title: "Grills",
        promotion_title_ar: "الشوايات",
        promotions: [{ name: "P1", title: "Grills", title_ar: "الشوايات", amount: 8 }],
      }),
    );

    expect(promotion).toEqual({ title: "الشوايات", amount: 8 });
  });

  it("falls back to the bill's own title when the server sent no list", () => {
    // An older server, or a bill built offline where the engine never ran.
    const { promotion } = reductionsOn(
      bill({
        discount_amount: 8,
        promotion_amount: 8,
        promotion_title: "Grills",
        promotion_title_ar: "الشوايات",
      }),
    );

    expect(promotion).toEqual({ title: "الشوايات", amount: 8 });
  });
});

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

/**
 * `D-171`. A refund row carries the **sale's** name so its card can wear the
 * sale's table and customer — and the obvious reading of a tap therefore opened
 * the sale. A cashier who returned two dishes off a bill of four got all four,
 * at positive prices, from a row labelled *refund*.
 *
 * This lives here rather than inline in the screen because that is the only way
 * to hold it. Breaking the routing left all 167 tests green until this existed,
 * which is exactly how the defect shipped.
 */
function row(extra: Partial<OpenOrder> = {}): OpenOrder {
  return {
    name: "RO-2026-09-00017",
    status: "closed",
    is_return: 0,
    credit_note: undefined,
    ...extra,
  } as OpenOrder;
}

describe("which document a row on the list opens", () => {
  it("opens the credit note for a refund, not the bill it reverses", () => {
    const target = whatOpens(row({ is_return: 1, credit_note: "ACC-SINV-2026-00011" }));

    expect(target).toEqual({ kind: "refund", creditNote: "ACC-SINV-2026-00011" });
  });

  it("opens the order for an ordinary row", () => {
    expect(whatOpens(row())).toEqual({ kind: "order", orderName: "RO-2026-09-00017" });
  });

  /**
   * `D-075` — a queued sale is one entry in a queue until the server has it.
   * Opening it would promise what nothing can keep.
   */
  it("opens nothing for a sale still waiting in the queue", () => {
    expect(whatOpens(row({ status: "queued" }))).toEqual({ kind: "queued" });
  });

  /**
   * A refund row whose credit note never arrived has nothing of its own to
   * show. The bill it reverses is the honest fallback — and it is the sale,
   * which is what the row's other fields already describe.
   */
  it("falls back to the bill when a refund row carries no credit note", () => {
    expect(whatOpens(row({ is_return: 1 }))).toEqual({
      kind: "order",
      orderName: "RO-2026-09-00017",
    });
  });
});
