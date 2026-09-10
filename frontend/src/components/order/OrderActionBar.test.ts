// @vitest-environment jsdom

/**
 * The sheet the user could not put away.
 *
 * `useDismiss` has its own tests; this one holds the **wiring** — that the
 * anchor ref is on the element wrapping the trigger and the sheet, and on that
 * one only. A ref left off, or put on the panel instead of the wrapper, breaks
 * exactly the way the bug was reported and breaks nothing a type-check can see.
 *
 * The sheet covers the item grid on the order screen, so a menu that will not
 * close is a till the cashier has to fight mid-queue.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OrderActionBar, { type OrderAction } from "@/components/order/OrderActionBar.vue";

const MORE: OrderAction[] = [
  { key: "return", label: "ret.action", icon: "swap" },
  { key: "cancel", label: "order.cancelOrder", icon: "ban", destructive: true },
];

/** Mount the bar with its sheet already open, attached so document taps land. */
async function openBar() {
  const wrapper = mount(OrderActionBar, {
    props: {
      actions: [{ key: "send", label: "order.sendToKitchen", icon: "kitchen", primary: true }],
      more: MORE,
    },
    attachTo: document.body,
  });

  await wrapper.get('[aria-expanded]').trigger("click");
  expect(wrapper.get('[aria-expanded]').attributes("aria-expanded")).toBe("true");
  return wrapper;
}

describe("OrderActionBar", () => {
  it("puts the sheet away when the tap lands elsewhere on the screen", async () => {
    const wrapper = await openBar();

    const elsewhere = document.createElement("div");
    document.body.appendChild(elsewhere);
    elsewhere.click();
    await wrapper.vm.$nextTick();

    expect(wrapper.get('[aria-expanded]').attributes("aria-expanded")).toBe("false");

    elsewhere.remove();
    wrapper.unmount();
  });

  it("stays open when the trigger itself is tapped open", async () => {
    // The opening tap reaches the document too; if the trigger sat outside the
    // anchor the sheet would never appear at all.
    const wrapper = await openBar();
    wrapper.unmount();
  });

  it("closes on Escape", async () => {
    const wrapper = await openBar();

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.vm.$nextTick();

    expect(wrapper.get('[aria-expanded]').attributes("aria-expanded")).toBe("false");
    wrapper.unmount();
  });
});
