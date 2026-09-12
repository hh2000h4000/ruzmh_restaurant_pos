// @vitest-environment jsdom

/**
 * The waiting screen the room reads (`FR-13.1`, `D-202`).
 *
 * The logo and the message are the only things on this screen a restaurant
 * writes itself, and both are optional. So the claims are about what happens
 * when they are **absent**: no broken image, and no rule drawn across the
 * screen above nothing — an empty divider reads as a restaurant that forgot
 * something, in front of the guest.
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import { IDLE, type DisplayState } from "@/composables/useCustomerDisplay";
import CustomerDisplayView from "@/views/CustomerDisplayView.vue";

let showing: DisplayState = { ...IDLE };

// The real receiver needs `BroadcastChannel`, which jsdom does not have; the
// channel itself is covered in `useCustomerDisplay.test.ts`.
vi.mock("@/composables/useCustomerDisplay", async (importActual) => ({
  ...(await importActual<typeof import("@/composables/useCustomerDisplay")>()),
  useCustomerDisplayReceiver: () => ({ state: ref(showing) }),
}));

function screen(state: Partial<DisplayState> = {}) {
  showing = { ...IDLE, ...state };
  return mount(CustomerDisplayView);
}

describe("the screen while it waits", () => {
  it("shows the restaurant's logo and its message", () => {
    const wrapper = screen({
      house: "مطعم الزيتون",
      logo: "/files/logo.png",
      message: "وجبة الغداء ٤٩ ريالاً",
    });

    const logo = wrapper.get("img");
    expect(logo.attributes("src")).toBe("/files/logo.png");
    // A picture that fails to load leaves the name, not a broken icon.
    expect(logo.attributes("alt")).toBe("مطعم الزيتون");
    expect(wrapper.get("[data-display-message]").text()).toBe("وجبة الغداء ٤٩ ريالاً");
  });

  it("draws neither when the restaurant has written neither", () => {
    const wrapper = screen({ house: "مطعم الزيتون" });

    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.find("[data-display-message]").exists()).toBe(false);
    expect(wrapper.text()).toContain("مطعم الزيتون");
  });

  it("keeps the message off the screen once a bill is on it", () => {
    const wrapper = screen({ mode: "order", message: "وجبة الغداء ٤٩ ريالاً", lines: [] });

    expect(wrapper.find("[data-display-message]").exists()).toBe(false);
  });
});

/**
 * `D-203` — what a restaurant's marketing actually is: a designed image, and
 * usually several. The layout claims are made on the classes, because jsdom
 * lays nothing out and applies no media query (as in `D-193`).
 */
describe("the banners", () => {
  const BANNERS = ["/files/offer-1.png", "/files/offer-2.png"];

  it("fill the screen while the till is idle, with the name and clock beneath", () => {
    const wrapper = screen({ house: "مطعم الزيتون", banners: BANNERS, seconds: 8 });

    expect(wrapper.find("[data-banner] img").attributes("src")).toBe(BANNERS[0]);
    expect(wrapper.text()).toContain("مطعم الزيتون");
  });

  it("take the larger side once a bill is open, and give way on a small screen", () => {
    const wrapper = screen({ mode: "order", banners: BANNERS, seconds: 8, lines: [] });

    const pane = wrapper.get("[data-banner-pane]");
    // The bill's own side is what remains, and below `lg` it is the whole width.
    expect(pane.classes()).toContain("max-lg:hidden");
    expect(wrapper.get("section").classes()).toContain("lg:grid-cols-[2fr_minmax(0,1fr)]");
  });

  it("are absent entirely for a restaurant that has none", () => {
    const idle = screen({ house: "مطعم الزيتون" });
    expect(idle.find("[data-banner]").exists()).toBe(false);

    const ordering = screen({ mode: "order", lines: [] });
    expect(ordering.find("[data-banner-pane]").exists()).toBe(false);
  });
});
