// @vitest-environment jsdom

/**
 * Opening a drawer asks for the cash in it, and nothing else (`D-329`).
 *
 * It listed every payment method on the terminal: a float box for a gift card
 * and one for HungerStation, and a dialog one row taller for each method added.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import OpenTillDialog from "@/components/shift/OpenTillDialog.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

function method(mode_of_payment: string, is_cash: 0 | 1, is_credit: 0 | 1 = 0) {
  return { mode_of_payment, is_cash, is_credit, default: 0 };
}

function dialog(methods: ReturnType<typeof method>[]) {
  useSessionStore().data = { pos_profile: { name: "T1" }, payment_methods: methods } as unknown as PosSession;
  return mount(OpenTillDialog, { props: { open: true }, global: { stubs: { teleport: true } } });
}

beforeEach(() => setActivePinia(createPinia()));

describe("what a drawer is asked when it opens", () => {
  it("lists no method when only one of them holds cash, however many there are", () => {
    const view = dialog([
      method("Cash", 1),
      method("Mada", 0),
      method("Gift Card", 0),
      method("HungerStation", 0, 1),
      method("Jahez", 0, 1),
    ]);

    expect(view.find("[data-methods]").exists()).toBe(false);
    expect(view.text()).not.toContain("HungerStation");
    expect(view.text()).not.toContain("Gift Card");
  });

  it("lists the cash methods, and only those, when there are two", () => {
    const view = dialog([method("Cash", 1), method("Cash USD", 1), method("Mada", 0)]);

    const listed = view.find("[data-methods]").text();
    expect(listed).toContain("Cash");
    expect(listed).toContain("Cash USD");
    expect(listed).not.toContain("Mada");
  });
});
