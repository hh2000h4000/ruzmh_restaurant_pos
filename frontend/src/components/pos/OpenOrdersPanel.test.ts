// @vitest-environment jsdom

/**
 * The switch that widens the open list, and the number on it (`D-164`, `D-168`).
 *
 * **The count is not decoration.** A switch that has to be turned on to learn
 * whether it holds three bills or three hundred hides the number as well as the
 * old mixed list did — and that list is how a shop came to be carrying a year of
 * bills without anyone deciding to (`D-158`).
 *
 * **And it is a switch rather than a tab**, which is the correction the user
 * asked for: a carried bill is an open bill, the tabs are statuses (`D-146`),
 * and Toast keeps unpaid checks from the previous day in the Open tab too.
 *
 * A component test because no backend gate can see a label: the endpoint can
 * count perfectly and the control still read nothing beside it, and the suite
 * would be green either way (`D-130`).
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { OpenOrder } from "@/api/order";
import OpenOrdersPanel from "@/components/pos/OpenOrdersPanel.vue";
import { t } from "@/i18n";

vi.mock("@/stores/session", () => ({
  useSessionStore: () => ({ can: () => true, profile: null, data: null }),
}));

function panel(props: Record<string, unknown> = {}) {
  return mount(OpenOrdersPanel, {
    props: {
      orders: [] as OpenOrder[],
      loading: false,
      error: null,
      searching: false,
      scope: null,
      view: "open",
      ...props,
    },
    global: { stubs: { AppIcon: true, teleport: true } },
  });
}

/** The tab strip's buttons, by their rendered text. */
function tabs(wrapper: ReturnType<typeof panel>) {
  return wrapper.findAll('[role="tab"]').map((button) => button.text());
}

describe("asking for the bills carried from a day that has ended", () => {
  it("is offered inside the open list, not as a tab of its own", () => {
    const wrapper = panel({ carriedCount: 312 });

    expect(tabs(wrapper)).toEqual([
      t("orders.viewOpen"),
      t("orders.viewClosed"),
      t("orders.viewReturned"),
      t("orders.viewAll"),
    ]);
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true);
  });

  it("wears the count, so nobody has to turn it on to learn the number", () => {
    expect(panel({ carriedCount: 312 }).text()).toContain(
      t("orders.showCarried", { count: "312" }),
    );
  });

  /**
   * An empty floor is the whole answer, and a control that is always there with
   * "(0)" beside it stops being read.
   */
  it("is not drawn at all when nothing is carried", () => {
    expect(panel({ carriedCount: 0 }).find('input[type="checkbox"]').exists()).toBe(false);
  });

  it("belongs to the open list and to no other tab", () => {
    const wrapper = panel({ carriedCount: 312, view: "closed" });

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
  });

  /**
   * The control has to say what it is doing. Unbound, the list widens and the
   * box stays empty — so the cashier taps it again and narrows it back, and the
   * carried bills flicker in and out with nothing explaining why.
   */
  it("shows whether it is on", () => {
    const on = panel({ carriedCount: 312, includeCarried: true });
    const off = panel({ carriedCount: 312, includeCarried: false });

    expect((on.find('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true);
    expect((off.find('input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false);
  });

  it("asks the screen to widen the list rather than filtering here", async () => {
    const wrapper = panel({ carriedCount: 312 });

    await wrapper.find('input[type="checkbox"]').setValue(true);

    expect(wrapper.emitted("update:includeCarried")).toEqual([[true]]);
  });
});
