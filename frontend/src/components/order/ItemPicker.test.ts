// @vitest-environment jsdom

/**
 * The menu has to hold every group the restaurant sells (`D-142`).
 *
 * A flow layout ran three across, which was a number written while looking at a
 * demo with six groups. The user asked the question that broke it: *what about
 * a shop with fifty?* — seventeen rows and a scroll on every order, and a
 * cashier hunting through a scrollbar is the slow till this product replaces.
 *
 * So the count picks the columns. These tests are the arithmetic of that, and
 * the reason they are worth writing is that the failure is invisible in
 * development: six groups look right at any setting.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import ItemPicker from "@/components/order/ItemPicker.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

function withTiles(count: number, mode: "flow" | "grid" = "flow") {
  useSessionStore().data = {
    items: [],
    item_groups: [],
    screen_layout: {
      name: "SL-TEST",
      title: "test",
      layout_mode: mode,
      grid_columns: 4,
      grid_rows: 4,
      background_color: null,
      buttons: Array.from({ length: count }, (_, index) => ({
        idx: index + 1,
        button_type: "item_group",
        item_group: `G${index}`,
        item: null,
        goto_screen: null,
        action_type: null,
        col_start: 1,
        col_span: 1,
        row_start: 1,
        row_span: 1,
        display_text: `G${index}`,
        display_text_ar: null,
        image: null,
        bg_color: null,
        text_color: null,
        font_size: null,
      })),
    },
  } as unknown as PosSession;

  return mount(ItemPicker, { props: { orderType: null } });
}

/** How many tracks the layout grid was given. */
function columnsOf(wrapper: ReturnType<typeof withTiles>): number {
  const grid = wrapper.findAll("div").find((el) => el.attributes("style")?.includes("grid-template-columns"));
  const declared = grid?.attributes("style")?.match(/repeat\((\d+),/);

  if (!declared) throw new Error("the layout grid declared no columns");
  return Number(declared[1]);
}

beforeEach(() => setActivePinia(createPinia()));

describe("fitting the groups on one screen", () => {
  it("keeps a small menu generous", () => {
    expect(columnsOf(withTiles(6))).toBe(3);
  });

  it.each([
    [12, 4],
    [20, 5],
    [30, 6],
    [42, 7],
    [50, 8],
  ])("puts %i groups in %i columns", (tiles, columns) => {
    expect(columnsOf(withTiles(tiles))).toBe(columns);
  });

  it("does not keep widening for ever", () => {
    // Past the last step the tiles shrink and, at the floor, it scrolls — a
    // twelve-column menu would be unreadable long before it was full.
    expect(columnsOf(withTiles(200))).toBe(8);
  });

  it("leaves a drawn grid at the width it was drawn", () => {
    expect(columnsOf(withTiles(50, "grid"))).toBe(4);
  });
});
