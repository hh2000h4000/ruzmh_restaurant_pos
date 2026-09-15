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

function layoutGrid(wrapper: ReturnType<typeof withTiles>) {
  const grid = wrapper.findAll("div").find((el) => el.attributes("style")?.includes("--columns"));
  if (!grid) throw new Error("the layout grid declared no columns");
  return grid;
}

/** How many tracks the layout grid was given, at most. */
function columnsOf(wrapper: ReturnType<typeof withTiles>): number {
  return Number((layoutGrid(wrapper).element as HTMLElement).style.getPropertyValue("--columns"));
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

  it("gives up a column on a phone rather than shrink a tile past its name", () => {
    // Thirteen groups on a 360 phone were five columns 46 points wide, and
    // "Desserts" read "Des". jsdom has no layout, so the rule is read off the
    // declaration: a track never narrower than the minimum, as many as fit.
    const style = layoutGrid(withTiles(13)).attributes("style") ?? "";

    expect(style).toContain("repeat(auto-fill, minmax(max(6rem, calc((100% - 4 * 0.875rem) / 5)), 1fr))");
  });
});

/**
 * `D-192` — the tiles carry pictures: the group's or dish's own, from ERPNext's
 * `image` field, and a drawn placeholder where there is none.
 */
describe("the pictures on the menu", () => {
  const groups = [
    {
      name: "Burgers",
      item_group_name: "برغر",
      image: "/files/burgers.png",
      parent_item_group: null,
      default_production_center: null,
    },
    {
      name: "Drinks",
      item_group_name: "مشروبات",
      image: null,
      parent_item_group: null,
      default_production_center: null,
    },
  ];

  function dish(code: string, group: string) {
    return {
      item_code: code,
      item_name: code,
      pos_display_name_ar: null,
      display_name: code,
      item_group: group,
      image: null,
      rate: 10,
      rates: {},
      modifier_groups: [],
    };
  }

  it("draws a group's own picture, and the placeholder for one without", () => {
    useSessionStore().data = {
      items: [dish("B1", "Burgers"), dish("D1", "Drinks")],
      item_groups: groups,
      screen_layout: null,
    } as unknown as PosSession;

    const wrapper = mount(ItemPicker, { props: { orderType: null } });

    const pictures = wrapper.findAll("[data-picture]");
    expect(pictures).toHaveLength(1);
    expect(pictures[0].attributes("src")).toBe("/files/burgers.png");
    expect(wrapper.findAll("[data-placeholder]")).toHaveLength(1);
  });

  it("gives a layout button its group's picture, and its colour to the strip", () => {
    useSessionStore().data = {
      items: [],
      item_groups: groups,
      screen_layout: {
        name: "SL-TEST",
        title: "test",
        layout_mode: "flow",
        grid_columns: 4,
        grid_rows: 4,
        background_color: null,
        buttons: [
          {
            idx: 1,
            button_type: "item_group",
            item_group: "Burgers",
            item: null,
            goto_screen: null,
            action_type: null,
            col_start: 1,
            col_span: 1,
            row_start: 1,
            row_span: 1,
            display_text: null,
            display_text_ar: null,
            image: null,
            bg_color: "rgb(139, 44, 44)",
            text_color: "rgb(255, 255, 255)",
            font_size: null,
          },
        ],
      },
    } as unknown as PosSession;

    const wrapper = mount(ItemPicker, { props: { orderType: null } });

    expect(wrapper.find("[data-picture]").attributes("src")).toBe("/files/burgers.png");
    expect(wrapper.find("[data-accent]").attributes("style")).toContain("rgb(139, 44, 44)");
    // White text was chosen for a coloured fill; on a white tile it would vanish.
    expect(wrapper.html()).not.toContain("color: rgb(255, 255, 255)");
    // The group's own name, not its record id, when the button carries no text.
    expect(wrapper.text()).toContain("برغر");
  });
});
