// @vitest-environment jsdom

/**
 * The card's menu puts itself away.
 *
 * `useDismiss` has its own tests and `OpenOrderRow` has the same one; this
 * exists because the card is **the other half of the same list** — the grid
 * shape of the rows — and the anchor ref is wired per component. Vue drops a
 * `ref` that matches nothing without a word, so a card left out of the fix
 * fails exactly the way the user reported and nothing else notices.
 *
 * Attached to the document on purpose: a detached card never sees the click
 * that this whole mechanism listens for.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { OpenOrder } from "@/api/order";
import OpenOrderCard from "@/components/pos/OpenOrderCard.vue";
import { t } from "@/i18n";

function card() {
  return mount(OpenOrderCard, {
    attachTo: document.body,
    props: {
      mayReprint: true,
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
        is_carried: 0,
        sales_invoice: "ACC-SINV-2026-00199",
      } as OpenOrder,
    },
  });
}

describe("the card's menu", () => {
  it("goes away when the tap lands on another card", async () => {
    const wrapper = card();

    // The options button, and the tap that opens the menu also reaches the
    // document — with no anchor it would close what it just opened.
    await wrapper.get(`[aria-label="${t("card.options")}"]`).trigger("click");
    expect(wrapper.text()).toContain(t("print.receiptAgain"));

    const elsewhere = document.createElement("div");
    document.body.appendChild(elsewhere);
    elsewhere.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.text()).not.toContain(t("print.receiptAgain"));

    elsewhere.remove();
    wrapper.unmount();
  });
});
