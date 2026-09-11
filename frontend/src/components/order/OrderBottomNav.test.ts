// @vitest-environment jsdom

/**
 * `D-194` — on a phone the five places stand their icon over their label.
 *
 * Beside their icons on a 412px Fold, every label was cut. jsdom lays nothing
 * out, so this holds what the markup promises; the widths were measured in a
 * browser, where nothing is cut at 412 or at 375.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OrderBottomNav, { type NavEntry } from "@/components/order/OrderBottomNav.vue";

const ENTRIES: NavEntry[] = [
  { key: "items", label: "order.paneItems", icon: "grid" },
  { key: "orders", label: "nav.orders", icon: "document", count: 5 },
];

describe("OrderBottomNav on a phone", () => {
  it("stacks the icon over the label", () => {
    const wrapper = mount(OrderBottomNav, { props: { entries: ENTRIES, active: "items" } });

    for (const entry of wrapper.findAll("[data-nav-entry]")) {
      expect(entry.classes()).toContain("max-sm:flex-col");
    }
  });

  it("carries the count beside the icon there, and behind the label where the row is wide", () => {
    const wrapper = mount(OrderBottomNav, { props: { entries: ENTRIES, active: "items" } });
    const icon = wrapper.findAll("[data-nav-entry]")[1].get("[data-nav-icon]");
    const count = icon.get(".rpos-numeric");

    // `contents` where the row is wide, so the count rejoins it and `order`
    // puts it after the label as before.
    expect(icon.classes()).toEqual(expect.arrayContaining(["contents", "max-sm:flex"]));
    expect(count.classes()).toContain("sm:order-last");
  });
});
