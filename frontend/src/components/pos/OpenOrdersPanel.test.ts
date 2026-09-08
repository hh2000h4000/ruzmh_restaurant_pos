// @vitest-environment jsdom

/**
 * The carried tab, and the number on it (`D-164`).
 *
 * **The count is not decoration.** A tab labelled "carried over" that has to be
 * opened to learn whether it holds three bills or three hundred hides the number
 * as well as the old mixed list did — and that list is how a shop came to be
 * carrying a year of bills without anyone deciding to (`D-158`).
 *
 * A component test because no backend gate can see a label: the endpoint can
 * count perfectly and the tab still read "carried over" with nothing beside it,
 * and the suite would be green either way (`D-130`).
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

describe("the tab that says how much is carried", () => {
  it("is offered beside the floor", () => {
    expect(tabs(panel())).toContain(t("orders.viewCarried"));
  });

  it("wears the count, so nobody has to open it to learn the number", () => {
    expect(tabs(panel({ carriedCount: 312 }))).toContain(`${t("orders.viewCarried")} (312)`);
  });

  /**
   * Nothing to clear is not a figure worth reading, and a badge that is always
   * there stops being noticed — which is the whole value of this one.
   */
  it("says nothing when there is nothing carried", () => {
    expect(tabs(panel({ carriedCount: 0 }))).toContain(t("orders.viewCarried"));
  });

  /**
   * The count is fetched separately from the list so a failed count cannot
   * empty a working floor. Offline it therefore arrives as whatever was last
   * known — and never as a confident zero, which is the one reading a cashier
   * would act on.
   */
  it("shows no number rather than a wrong one when none was fetched", () => {
    expect(tabs(panel())).toContain(t("orders.viewCarried"));
  });

  it("tells the cashier the backlog is clear rather than showing an empty box", () => {
    const wrapper = panel({ view: "carried", orders: [] });

    expect(wrapper.text()).toContain(t("orders.emptyCarried"));
  });
});
