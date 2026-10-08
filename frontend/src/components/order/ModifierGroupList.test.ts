// @vitest-environment jsdom

/**
 * An add-on that sells something off the shelf says when the shelf is empty (`D-336`).
 *
 * The server refuses extra cheese it has not got (`D-335`), but it refused the
 * whole line: the burger did not reach the bill and the cashier was told
 * afterwards. Said on the option, in the popup, they do not choose it.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { ModifierGroup, ModifierOption } from "@/api/modifiers";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import ModifierGroupList from "@/components/order/ModifierGroupList.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useStockStore } from "@/stores/stock";
import type { CatalogItem, PosSession } from "@/types/session";

function option(title: string, extra: Partial<ModifierOption> = {}): ModifierOption {
  return { title, title_ar: title, price_effect: "add", price_amount: 2, is_default: 0, ...extra };
}

const EXTRAS: ModifierGroup = {
  name: "Extras",
  title: "Extras",
  title_ar: "Extras",
  selection_type: "multiple",
  is_required: 0,
  min_selections: 0,
  max_selections: 0,
  options: [
    option("Extra cheese", { sells_item: "CHEESE" }),
    option("Extra patty", { sells_item: "PATTY" }),
    // Leaves an ingredient out: sells nothing, so the shelf has no say in it.
    option("No bun", { sells_item: null, price_effect: "none", price_amount: 0 }),
  ],
} as ModifierGroup;

function list() {
  return mount(ModifierGroupList, { props: { groups: [EXTRAS], chosen: {} } });
}

function button(view: ReturnType<typeof list>, title: string) {
  return view.findAll("button").find((one) => one.text().includes(title))!;
}

beforeEach(() => setActivePinia(createPinia()));

describe("an add-on whose item is finished", () => {
  it("says nothing while there is some left", () => {
    useStockStore().left = { CHEESE: 3 };
    const view = list();

    expect(button(view, "Extra cheese").find("[data-finished]").exists()).toBe(false);
    expect(button(view, "Extra cheese").attributes("disabled")).toBeUndefined();
  });

  it("says sold out and cannot be chosen, where the branch enforces its stock", async () => {
    const stock = useStockStore();
    stock.enforced = true;
    stock.left = { CHEESE: -14 };
    const view = list();

    await button(view, "Extra cheese").trigger("click");

    expect(button(view, "Extra cheese").find("[data-finished]").text()).toBe(t("stock.soldOut"));
    expect(button(view, "Extra cheese").attributes("disabled")).toBeDefined();
    expect(view.emitted("toggle")).toBeUndefined();
    // The others are untouched.
    expect(button(view, "Extra patty").attributes("disabled")).toBeUndefined();
    expect(button(view, "No bun").attributes("disabled")).toBeUndefined();
  });

  it("says so and can still be chosen, where the branch does not", async () => {
    useStockStore().left = { CHEESE: 0 };
    const view = list();

    await button(view, "Extra cheese").trigger("click");

    expect(button(view, "Extra cheese").find("[data-finished]").exists()).toBe(true);
    expect(view.emitted("toggle")).toHaveLength(1);
  });

  it("cannot be chosen in any branch once a person marked it finished", () => {
    useStockStore().soldOut = new Set(["PATTY"]);
    const view = list();

    expect(button(view, "Extra patty").attributes("disabled")).toBeDefined();
  });
});

describe("a default add-on that is finished", () => {
  function dish(defaultCheese: 0 | 1) {
    const group = {
      ...EXTRAS,
      options: [option("Extra cheese", { sells_item: "CHEESE", is_default: defaultCheese })],
    } as ModifierGroup;
    useSessionStore().data = { modifier_groups: [group] } as unknown as PosSession;
    return mount(ModifierDialog, {
      props: { item: { item_code: "BURGER", item_name: "Burger", modifier_groups: ["Extras"] } as unknown as CatalogItem },
      global: { stubs: { teleport: true } },
    });
  }

  it("is not chosen for the cashier: they could not take it off again", () => {
    const stock = useStockStore();
    stock.enforced = true;
    stock.left = { CHEESE: 0 };

    const view = dish(1);

    expect(button(view as never, "Extra cheese").attributes("aria-pressed")).toBe("false");
  });

  it("is chosen as usual while there is some", () => {
    useStockStore().left = { CHEESE: 5 };

    const view = dish(1);

    expect(button(view as never, "Extra cheese").attributes("aria-pressed")).toBe("true");
  });
});
