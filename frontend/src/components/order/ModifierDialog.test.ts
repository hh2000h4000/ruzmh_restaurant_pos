// @vitest-environment jsdom

/**
 * A combo item's own groups show while that item is the one chosen (`D-289`).
 *
 * «Extra cheese» belongs to the burger. In a meal where the guest picks the
 * burger or the chicken, asking about cheese before anyone chose the burger —
 * or requiring an answer after they chose the chicken — would stop a sale over
 * a question that does not apply. The server prices whatever is sent, so the
 * popup must not send a hidden group's answer either.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { ModifierGroup } from "@/api/modifiers";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import { useSessionStore } from "@/stores/session";
import type { CatalogItem, PosSession } from "@/types/session";

const MAIN = "combo:MEAL:Main";
const CHEESE = "combo-part:MEAL|BURGER|Extras";

function option(title: string, title_ar: string, price_amount = 0) {
  return {
    title,
    title_ar,
    price_effect: price_amount ? ("add" as const) : ("none" as const),
    price_amount,
    is_default: 0 as const,
  };
}

const groups: ModifierGroup[] = [
  {
    name: MAIN,
    title: "Main",
    title_ar: "الرئيسي",
    selection_type: "single",
    is_required: 1,
    min_selections: 1,
    max_selections: 1,
    options: [option("BURGER", "برغر"), option("CHICKEN", "دجاج")],
  },
  {
    name: CHEESE,
    title: "Extras",
    title_ar: "إضافات — برغر",
    selection_type: "multiple",
    is_required: 1,
    min_selections: 1,
    max_selections: 0,
    options: [option("Extra cheese", "جبنة إضافية", 2)],
    when: { group: MAIN, option: "BURGER" },
  },
];

function dialog() {
  return mount(ModifierDialog, {
    props: {
      item: {
        item_code: "MEAL",
        item_name: "Meal",
        pos_display_name_ar: "وجبة",
        modifier_groups: [MAIN, CHEESE],
      } as unknown as CatalogItem,
    },
    global: { stubs: { teleport: true } },
  });
}

beforeEach(() => {
  setActivePinia(createPinia());
  useSessionStore().data = { modifier_groups: groups } as unknown as PosSession;
});

describe("a combo item's own groups", () => {
  it("are not asked until their item is chosen", () => {
    const wrapper = dialog();
    expect(wrapper.text()).not.toContain("جبنة إضافية");
  });

  it("appear when their item is chosen, and are asked like any group", async () => {
    const wrapper = dialog();
    await wrapper.findAll("button").find((button) => button.text() === "برغر")!.trigger("click");

    expect(wrapper.text()).toContain("جبنة إضافية");
  });

  it("are neither required nor sent for another item", async () => {
    const wrapper = dialog();
    await wrapper.findAll("button").find((button) => button.text() === "دجاج")!.trigger("click");

    const add = wrapper.findAll("button").at(-1)!;
    expect(add.attributes("disabled")).toBeUndefined();
    await add.trigger("click");

    const sent = wrapper.emitted("confirm")![0][0] as { modifiers: { group: string }[] };
    expect(sent.modifiers).toEqual([{ group: MAIN, option: "CHICKEN" }]);
  });
});
