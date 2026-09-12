// @vitest-environment jsdom

/**
 * The banners turning on the screen facing the room (`FR-13.1`, `D-203`).
 *
 * This screen runs all day in front of a queue, so the two claims that matter
 * are that it **moves** on the manager's schedule, and that it **stops** asking
 * the browser to redraw when there is nothing to change.
 */
import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DisplayBanner from "@/components/display/DisplayBanner.vue";

const BANNERS = ["/files/offer-1.png", "/files/offer-2.png", "/files/offer-3.png"];

function shown(wrapper: ReturnType<typeof mount>) {
  return wrapper.find("img").attributes("src");
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("a banner in its turn", () => {
  it("moves to the next one after the seconds the manager set", async () => {
    const wrapper = mount(DisplayBanner, { props: { banners: BANNERS, seconds: 8 } });

    expect(shown(wrapper)).toBe(BANNERS[0]);

    vi.advanceTimersByTime(8000);
    await wrapper.vm.$nextTick();
    expect(shown(wrapper)).toBe(BANNERS[1]);
  });

  it("comes round again after the last one", async () => {
    const wrapper = mount(DisplayBanner, { props: { banners: BANNERS, seconds: 5 } });

    vi.advanceTimersByTime(5000 * 3);
    await wrapper.vm.$nextTick();

    expect(shown(wrapper)).toBe(BANNERS[0]);
  });

  it("runs no timer for a single banner, which would change nothing", () => {
    const spy = vi.spyOn(window, "setInterval");

    mount(DisplayBanner, { props: { banners: [BANNERS[0]], seconds: 8 } });

    expect(spy).not.toHaveBeenCalled();
  });

  /**
   * One second, not zero. A floor removed makes the interval whatever the desk
   * typed, and `setInterval(fn, 0)` under fake timers re-arms itself faster than
   * the clock advances: the mutation that removes this floor **hung the runner
   * for thirty-five minutes** rather than failing. A test has to fail fast to be
   * worth anything.
   */
  it("refuses a turn too short to read", async () => {
    const wrapper = mount(DisplayBanner, { props: { banners: BANNERS, seconds: 1 } });

    vi.advanceTimersByTime(1000);
    await wrapper.vm.$nextTick();
    expect(shown(wrapper)).toBe(BANNERS[0]);

    vi.advanceTimersByTime(1000);
    await wrapper.vm.$nextTick();
    expect(shown(wrapper)).toBe(BANNERS[1]);
  });

  it("draws nothing at all when there are no banners", () => {
    const wrapper = mount(DisplayBanner, { props: { banners: [], seconds: 8 } });

    expect(wrapper.find("[data-banner]").exists()).toBe(false);
  });
});
