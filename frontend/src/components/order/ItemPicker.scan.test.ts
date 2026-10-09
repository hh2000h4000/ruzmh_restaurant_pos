// @vitest-environment jsdom

/**
 * A barcode reader adds the item it read (`D-341`).
 *
 * A reader is a keyboard that types fast and presses Enter. It is heard in the
 * search box, and anywhere on the screen when no field has the focus — and the
 * code is looked up in the menu the till already holds, so a scan asks the
 * server nothing.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import ItemPicker from "@/components/order/ItemPicker.vue";
import { useSessionStore } from "@/stores/session";
import { useStockStore } from "@/stores/stock";
import type { CatalogItem, PosSession } from "@/types/session";

const WATER = "6281000000017";

function item(code: string, name: string, barcodes: string[] = []): CatalogItem {
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
    barcodes,
  };
}

let mounted: ReturnType<typeof mount> | null = null;

function picker(props: Record<string, unknown> = {}) {
  useSessionStore().data = {
    pos_profile: { name: "TILL-1" },
    items: [item("WATER", "Water", [WATER]), item("JUICE", "Juice"), item("SOUP", "Soup")],
    item_groups: [{ name: "Drinks", item_group_name: "Drinks", image: null, parent_item_group: null }],
    screen_layout: null,
  } as unknown as PosSession;

  mounted = mount(ItemPicker, { props: { orderType: null, ...props }, attachTo: document.body });
  return mounted;
}

/** What a reader does: the digits, then Enter, with no field focused. */
function scan(code: string, target: EventTarget = document.body): void {
  for (const key of [...code, "Enter"]) {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  }
}

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => {
  mounted?.unmount();
  mounted = null;
  document.body.innerHTML = "";
});

describe("a scan with no field focused", () => {
  it("adds the item the code belongs to", () => {
    const view = picker();

    scan(WATER);

    expect(view.emitted("pick")).toHaveLength(1);
    expect((view.emitted("pick")![0][0] as CatalogItem).item_code).toBe("WATER");
  });

  it("says so when no item has that code", () => {
    const view = picker();

    scan("9999999999999");

    expect(view.emitted("pick")).toBeUndefined();
    expect(String(view.emitted("failed")![0][0])).toContain("9999999999999");
  });

  it("says so when the item is sold out, rather than beeping at nothing", () => {
    const stock = useStockStore();
    stock.enforced = true;
    stock.left = { WATER: 0 };
    const view = picker();

    scan(WATER);

    expect(view.emitted("pick")).toBeUndefined();
    expect(view.emitted("failed")).toHaveLength(1);
  });

  it("is not heard while a dialog is open over the menu", () => {
    const view = picker();
    const sheet = document.createElement("div");
    sheet.setAttribute("role", "dialog");
    document.body.appendChild(sheet);

    scan(WATER);

    expect(view.emitted("pick")).toBeUndefined();
  });

  it("is not a scan when the keys came slowly", async () => {
    const view = picker();

    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "6", bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 150));
    scan("281");

    expect(view.emitted("pick")).toBeUndefined();
    expect(view.emitted("failed")).toBeUndefined();
  });
});

describe("the search box", () => {
  it("adds the item when a code is typed into it and Enter pressed, and clears itself", async () => {
    const view = picker();
    const box = view.find("#item-search");

    await box.setValue(WATER);
    await box.trigger("keydown", { key: "Enter" });

    expect((view.emitted("pick")![0][0] as CatalogItem).item_code).toBe("WATER");
    expect((box.element as HTMLInputElement).value).toBe("");
  });

  it("adds the one dish the words left", async () => {
    const view = picker();
    const box = view.find("#item-search");

    await box.setValue("jui");
    await box.trigger("keydown", { key: "Enter" });

    expect((view.emitted("pick")![0][0] as CatalogItem).item_code).toBe("JUICE");
  });

  it("adds nothing while the words still fit several", async () => {
    const view = picker();
    const box = view.find("#item-search");

    await box.setValue("u");
    await box.trigger("keydown", { key: "Enter" });

    expect(view.emitted("pick")).toBeUndefined();
  });

  it("keeps a scan typed into it to itself: one item, not two", async () => {
    const view = picker();
    const box = view.find("#item-search");

    await box.setValue(WATER);
    scan(WATER, box.element);

    expect(view.emitted("pick")).toHaveLength(1);
  });
});
