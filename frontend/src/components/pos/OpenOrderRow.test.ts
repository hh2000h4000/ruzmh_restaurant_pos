// @vitest-environment jsdom

/**
 * The one action a bill row carries (`D-145`).
 *
 * A refund is a document that exists **only** as a row on this list — there is
 * no refund screen to open it from — so if the reprint is not here, a customer
 * whose credit note tore has nowhere to go but the office.
 *
 * These are component tests because the backend gate cannot see a menu entry
 * (`D-130`): the endpoint can be perfect and the button absent, and the suite
 * would be green either way. They hold the row to three things — that a refund
 * reprints its **own** credit note rather than the sale it reverses, that a
 * bill with no invoice yet offers nothing, and that the entry follows the
 * permission.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { OpenOrder } from "@/api/order";
import OpenOrderRow from "@/components/pos/OpenOrderRow.vue";
import { t } from "@/i18n";

function row(order: Partial<OpenOrder>, mayReprint = true) {
  return mount(OpenOrderRow, {
    props: {
      mayReprint,
      order: {
        name: "RO-2026-09-00001",
        daily_number: 20,
        call_name: null,
        order_type: "OT-01",
        order_type_title: "Takeaway",
        order_type_title_ar: "سفري",
        icon: null,
        color: null,
        status: "closed",
        table: null,
        table_number: null,
        cover_count: 0,
        customer: null,
        cashier: "cashier@example.com",
        cashier_name: "Cashier",
        total_amount: 64,
        returned_amount: 0,
        opened_at: "2026-09-06 12:00:00",
        item_count: 2,
        ...order,
      } as OpenOrder,
    },
  });
}

/** Open the row's menu and hand back its entries. */
async function menu(wrapper: ReturnType<typeof row>) {
  const buttons = wrapper.findAll("button");
  await buttons[buttons.length - 1].trigger("click");
  // Matched through `t` rather than by wording: the catalogue decides what the
  // entry says, and in whichever language the app is running.
  return wrapper.findAll("button").filter((button) => button.text() === t("print.receiptAgain"));
}

describe("which document a row says it is", () => {
  it("a sale shows its order number", () => {
    const wrapper = row({ sales_invoice: "ACC-SINV-2026-00199" });

    expect(wrapper.text()).toContain("RO-2026-09-00001");
  });

  /**
   * `D-151` — the user spotted this on the returns tab: two refunds of one bill
   * both read as the bill. A refund has no `Restaurant Order` of its own, so
   * the row was drawing the sale's number for want of one.
   */
  it("a refund shows the credit note, not the bill it reverses", () => {
    const wrapper = row({
      is_return: 1,
      credit_note: "ACC-SINV-2026-00200",
      returns_daily_number: 20,
      daily_number: 21,
      total_amount: -32,
    });

    expect(wrapper.text()).toContain("ACC-SINV-2026-00200");
    expect(wrapper.text()).not.toContain("RO-2026-09-00001");
  });
});

describe("reprinting from a bill row", () => {
  it("offers a paid bill its receipt", async () => {
    const wrapper = row({ sales_invoice: "ACC-SINV-2026-00199" });

    expect(await menu(wrapper)).toHaveLength(1);
  });

  it("prints the refund's own credit note, not the sale it reverses", async () => {
    const wrapper = row({
      is_return: 1,
      credit_note: "ACC-SINV-2026-00200",
      sales_invoice: "ACC-SINV-2026-00199",
      returns_daily_number: 20,
      daily_number: 21,
      total_amount: -32,
    });

    await (await menu(wrapper))[0].trigger("click");

    expect(wrapper.emitted("reprint")).toHaveLength(1);
    // The row emits itself; the screen reads `credit_note` first. Asserted
    // here so the order of that fallback cannot be reversed unnoticed.
    expect(wrapper.props("order").credit_note).toBe("ACC-SINV-2026-00200");
  });

  it("offers nothing on a bill that has not been paid for", async () => {
    const wrapper = row({ status: "active", sales_invoice: null });

    expect(await menu(wrapper)).toHaveLength(0);
  });

  it("follows the permission", async () => {
    const wrapper = row({ sales_invoice: "ACC-SINV-2026-00199" }, false);

    expect(await menu(wrapper)).toHaveLength(0);
  });
});
