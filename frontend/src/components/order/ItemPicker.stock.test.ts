// @vitest-environment jsdom

/**
 * What a tile says about stock, and marking what is finished (`D-321`, `D-322`).
 *
 * The server decides whether a line is sold; this screen only has to say the
 * truth it was told — nothing when there is plenty, a number when there is
 * little, "sold out" when there is none — and, in marking mode, to make a tap
 * mean "finished" instead of "add".
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/availability";
import ItemPicker from "@/components/order/ItemPicker.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useStockStore } from "@/stores/stock";
import type { CatalogItem, PosSession } from "@/types/session";

vi.mock("@/api/availability", () => ({ getStock: vi.fn(), setSoldOut: vi.fn() }));

function item(code: string, name: string): CatalogItem {
  return {
    item_code: code,
    item_name: name,
    pos_display_name_ar: null,
    display_name: name,
    item_group: "Drinks",
    stock_uom: "Nos",
    image: null,
    default_production_center: null,
    rate: 5,
    rates: {},
    modifier_groups: [],
  };
}

function picker(props: Record<string, unknown> = {}) {
  useSessionStore().data = {
    pos_profile: { name: "TILL-1" },
    items: [item("WATER", "Water"), item("JUICE", "Juice"), item("SOUP", "Soup")],
    item_groups: [{ name: "Drinks", item_group_name: "Drinks", image: null, parent_item_group: null }],
    screen_layout: null,
  } as unknown as PosSession;

  return mount(ItemPicker, { props: { orderType: null, ...props } });
}

/** Open the only group, so the dishes are on screen. */
async function dishes(view: ReturnType<typeof picker>) {
  await view.findAll("button").find((one) => one.text().includes("Drinks"))!.trigger("click");
  return view;
}

function tileOf(view: ReturnType<typeof picker>, name: string) {
  return view.findAll("button").find((one) => one.text().includes(name))!;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("what a tile says about stock", () => {
  it("says nothing when there is plenty", async () => {
    const view = await dishes(picker());

    expect(tileOf(view, "Water").find("[data-badge]").exists()).toBe(false);
  });

  it("says how many are left when there are few", async () => {
    const view = picker();
    useStockStore().left = { WATER: 8 };
    await dishes(view);

    expect(tileOf(view, "Water").find("[data-badge]").text()).toBe(t("stock.left", { count: "8" }));
    expect(tileOf(view, "Water").attributes("disabled")).toBeUndefined();
  });

  it("says sold out and does not offer it, where the branch enforces its stock", async () => {
    const view = picker();
    const stock = useStockStore();
    stock.enforced = true;
    stock.left = { WATER: 0 };
    await dishes(view);

    expect(tileOf(view, "Water").find("[data-badge]").text()).toBe(t("stock.soldOut"));
    expect(tileOf(view, "Water").attributes("disabled")).toBeDefined();
  });

  it("says so and still sells it, where the branch does not", async () => {
    const view = picker();
    useStockStore().left = { WATER: 0 };
    await dishes(view);

    await tileOf(view, "Water").trigger("click");

    expect(tileOf(view, "Water").find("[data-badge]").text()).toBe(t("stock.soldOut"));
    expect(view.emitted("pick")).toHaveLength(1);
  });

  it("never offers what a person marked as finished, in any branch", async () => {
    const view = picker();
    useStockStore().soldOut = new Set(["SOUP"]);
    await dishes(view);

    await tileOf(view, "Soup").trigger("click");

    expect(tileOf(view, "Soup").attributes("disabled")).toBeDefined();
    expect(view.emitted("pick")).toBeUndefined();
  });
});

describe("marking what is finished for today", () => {
  it("marks instead of adding, and says what a tap means", async () => {
    vi.mocked(api.setSoldOut).mockResolvedValue({ sold_out: ["SOUP"] });
    const view = await dishes(picker({ marking: true }));

    await tileOf(view, "Soup").trigger("click");
    await flushPromises();

    expect(view.find("[data-marking]").text()).toContain(t("stock.markingHint"));
    expect(api.setSoldOut).toHaveBeenCalledWith("TILL-1", "SOUP", true);
    expect(view.emitted("pick")).toBeUndefined();
    expect(tileOf(view, "Soup").find("[data-badge]").text()).toBe(t("stock.soldOut"));
  });

  it("brings a marked one back on the second tap", async () => {
    vi.mocked(api.setSoldOut).mockResolvedValue({ sold_out: [] });
    const view = picker({ marking: true });
    useStockStore().soldOut = new Set(["SOUP"]);
    await dishes(view);

    await tileOf(view, "Soup").trigger("click");
    await flushPromises();

    expect(api.setSoldOut).toHaveBeenCalledWith("TILL-1", "SOUP", false);
    expect(tileOf(view, "Soup").find("[data-badge]").exists()).toBe(false);
  });

  it("works on a bill that is locked: it is about the branch, not the bill", async () => {
    vi.mocked(api.setSoldOut).mockResolvedValue({ sold_out: ["SOUP"] });
    const view = await dishes(picker({ marking: true, disabled: true }));

    await tileOf(view, "Soup").trigger("click");
    await flushPromises();

    expect(api.setSoldOut).toHaveBeenCalled();
  });

  it("hands back what the server refused", async () => {
    vi.mocked(api.setSoldOut).mockRejectedValue(new Error("no"));
    const view = await dishes(picker({ marking: true }));

    await tileOf(view, "Soup").trigger("click");
    await flushPromises();

    expect(view.emitted("failed")).toHaveLength(1);
  });

  it("leaves when done is tapped", async () => {
    const view = picker({ marking: true });

    await view.find("[data-marking] button").trigger("click");

    expect(view.emitted("done")).toHaveLength(1);
  });
});
