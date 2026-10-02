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
const SAUCE = "combo-part:MEAL|CHICKEN|Sauce";

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
    part: { item: "BURGER", title: "Burger", title_ar: "برغر" },
  },
  {
    name: SAUCE,
    title: "Sauce",
    title_ar: "صوص — دجاج",
    selection_type: "single",
    is_required: 0,
    min_selections: 0,
    max_selections: 1,
    options: [option("Garlic", "ثوم")],
    when: { group: MAIN, option: "CHICKEN" },
    part: { item: "CHICKEN", title: "Chicken", title_ar: "دجاج" },
  },
];

function dialog() {
  return mount(ModifierDialog, {
    props: {
      item: {
        item_code: "MEAL",
        item_name: "Meal",
        pos_display_name_ar: "وجبة",
        modifier_groups: [MAIN, CHEESE, SAUCE],
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

  it("open by themselves over the combo when the chosen item must be answered", async () => {
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

  /**
   * The owner's complaint (D-292): every chosen item's add-ons laid out under
   * the combo ran it off the screen. An optional question waits behind a button.
   */
  it("keep an optional question behind a button, with a line of what was picked", async () => {
    const wrapper = dialog();
    await wrapper.findAll("button").find((button) => button.text() === "دجاج")!.trigger("click");

    expect(wrapper.text()).not.toContain("ثوم");
    await wrapper.find("[data-combo-part-edit]").trigger("click");
    await wrapper.findAll("button").find((button) => button.text() === "ثوم")!.trigger("click");
    await wrapper.find("[data-combo-part-done]").trigger("click");

    expect(wrapper.find("[data-combo-part-summary]").text()).toContain("ثوم");
  });
});
