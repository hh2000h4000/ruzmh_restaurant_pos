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
