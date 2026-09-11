// @vitest-environment jsdom

/**
 * The menu tile (`D-192`): a picture when there is one, a placeholder when
 * there is not — and never a broken-image box.
 *
 * The last one is the case worth a test. A picture that fails to load — the
 * till offline, a file deleted in the desk — drew the browser's broken-image
 * mark in a card a cashier reads a hundred times a shift, and nothing about it
 * says what to do.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import MenuTile from "@/components/order/MenuTile.vue";

function tile(props: Record<string, unknown> = {}) {
  return mount(MenuTile, { props: { label: "برغر", ...props } });
}

describe("the picture on a menu tile", () => {
  it("shows the group's or dish's own picture", () => {
    const wrapper = tile({ image: "/files/burger.png" });

    expect(wrapper.find("[data-picture]").attributes("src")).toBe("/files/burger.png");
    expect(wrapper.find("[data-placeholder]").exists()).toBe(false);
  });

  it("draws the placeholder when there is none", () => {
    const wrapper = tile({ image: null });

    expect(wrapper.find("[data-picture]").exists()).toBe(false);
    expect(wrapper.find("[data-placeholder]").exists()).toBe(true);
  });

  it("falls back to the placeholder when the picture will not load", async () => {
    const wrapper = tile({ image: "/files/deleted.png" });

    await wrapper.find("[data-picture]").trigger("error");

    expect(wrapper.find("[data-picture]").exists()).toBe(false);
    expect(wrapper.find("[data-placeholder]").exists()).toBe(true);
  });

  it("gives a new picture a new chance after a failed one", async () => {
    const wrapper = tile({ image: "/files/deleted.png" });
    await wrapper.find("[data-picture]").trigger("error");

    await wrapper.setProps({ image: "/files/uploaded-again.png" });

    expect(wrapper.find("[data-picture]").attributes("src")).toBe("/files/uploaded-again.png");
  });
});

describe("the rest of the tile", () => {
  it("puts a configured colour on the strip, not on the card", () => {
    const wrapper = tile({ accent: "rgb(139, 44, 44)" });

    expect(wrapper.find("[data-accent]").attributes("style")).toContain("rgb(139, 44, 44)");
    expect(wrapper.attributes("style") ?? "").not.toContain("background");
  });

  it("carries the price under the name", () => {
    expect(tile({ detail: "25.00" }).text()).toContain("25.00");
  });

  it("does not answer a tap when disabled", async () => {
    const wrapper = tile({ disabled: true });

    await wrapper.trigger("click");

    expect(wrapper.emitted("select")).toBeUndefined();
  });
});
