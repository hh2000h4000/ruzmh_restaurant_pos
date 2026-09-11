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

/**
 * `D-194` — on a 412px Fold the four labelled buttons broke onto a second line.
 * jsdom lays nothing out, so these hold what the markup promises; the row was
 * measured on one line in a browser.
 */
describe("OrderActionBar on a phone", () => {
  const ROW: OrderAction[] = [
    { key: "send", label: "order.sendToKitchen", icon: "kitchen", primary: true },
    { key: "notes", label: "note.orderAction", icon: "note" },
  ];

  /** The label is the last span in a button, after whatever the icon draws. */
  function label(button: ReturnType<ReturnType<typeof mount>["get"]>) {
    return button.findAll("span").at(-1)!;
  }

  it("keeps the primary's words and folds the rest to icons that still carry their names", () => {
    const wrapper = mount(OrderActionBar, { props: { actions: ROW, more: MORE } });
    const [send, note, more] = wrapper.findAll("button");

    expect(label(send).classes()).not.toContain("max-sm:sr-only");
    expect(label(note).classes()).toContain("max-sm:sr-only");
    expect(label(more).classes()).toContain("max-sm:sr-only");
    // Hidden from the eye, not from a screen reader: the words are still there.
    expect(note.text()).not.toBe("");
  });

  it("stays on one line, and opens its sheet back across the screen from the edge", async () => {
    const wrapper = mount(OrderActionBar, { props: { actions: ROW, more: MORE }, attachTo: document.body });

    expect(wrapper.classes()).toContain("max-sm:flex-nowrap");

    await wrapper.get("[aria-expanded]").trigger("click");
    expect(wrapper.get("[aria-expanded] + div").classes()).toContain("max-sm:end-0");
    wrapper.unmount();
  });
});
