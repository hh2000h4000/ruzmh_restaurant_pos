// @vitest-environment jsdom

/**
 * A dish priced at the counter asks for its price before it is added (`D-378`).
 *
 * The fish of the day has no row in any price list. Its tile still takes a tap,
 * reads «open price» where a price would be, and opens the keypad; only a price
 * above zero adds it, and closing the pad adds nothing.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import type { CatalogItem, PosSession } from "@/types/session";

const FISH = "6281000000024";

const fish: CatalogItem = {
  item_code: "FISH",
  item_name: "Fish of the day",
  pos_display_name_ar: null,
  display_name: "Fish of the day",
  item_group: "Mains",
  stock_uom: "Nos",
  image: null,
  default_production_center: null,
  rate: null,
  rates: {},
  modifier_groups: [],
  barcodes: [FISH],
  open_price: 1,
};

let mounted: ReturnType<typeof mount> | null = null;

function picker() {
  useSessionStore().data = {
    pos_profile: { name: "TILL-1" },
    items: [fish],
    item_groups: [{ name: "Mains", item_group_name: "Mains", image: null, parent_item_group: null }],
    screen_layout: null,
  } as unknown as PosSession;

  mounted = mount(ItemPicker, { props: { orderType: null }, attachTo: document.body });
  return mounted;
}

function scan(code: string): void {
  for (const key of [...code, "Enter"]) {
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  }
}

function done(): HTMLButtonElement {
  return [...document.querySelectorAll<HTMLButtonElement>("[role=dialog] button")].find(
    (button) => button.textContent?.trim() === t("action.done"),
  )!;
}

beforeEach(() => setActivePinia(createPinia()));
afterEach(() => {
  mounted?.unmount();
  mounted = null;
  document.body.innerHTML = "";
});

describe("a dish priced at the counter", () => {
  it("asks for the price, and adds it at that price", async () => {
    const view = picker();

    scan(FISH);
    await flushPromises();
    expect(view.emitted("pick")).toBeUndefined();
    expect(done().disabled).toBe(true);

    view.findComponent(AmountKeypad).vm.$emit("update", "42.5");
    await flushPromises();
    done().click();
    await flushPromises();

    const [item, qty, rate] = view.emitted("pick")![0];
    expect((item as CatalogItem).item_code).toBe("FISH");
    expect(qty).toBe(1);
    expect(rate).toBe(42.5);
  });

  it("adds nothing when the pad is closed", async () => {
    const view = picker();

    scan(FISH);
    await flushPromises();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await flushPromises();

    expect(document.querySelector("[role=dialog]")).toBeNull();
    expect(view.emitted("pick")).toBeUndefined();
  });
});
