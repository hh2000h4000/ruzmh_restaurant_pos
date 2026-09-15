// @vitest-environment jsdom

/**
 * `D-220` — the notice floats, says what happened, and closes when asked.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import AppToast from "@/components/AppToast.vue";
import { useNoticeStore } from "@/stores/notice";

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("the notice", () => {
  it("keeps both live regions in the page before anything is said", () => {
    // A region inserted with its words already inside is often not announced.
    const toast = mount(AppToast);

    expect(toast.find('[role="status"]').exists()).toBe(true);
    expect(toast.find('[role="alert"]').exists()).toBe(true);
    expect(toast.text()).toBe("");
  });

  it("says news politely, and closes when the cashier taps it away", async () => {
    const notice = useNoticeStore();
    const toast = mount(AppToast);

    notice.info("Receipt 12 sent to the printer");
    await toast.vm.$nextTick();
    expect(toast.find('[role="status"]').text()).toContain("Receipt 12 sent to the printer");

    await toast.find('[role="status"] button').trigger("click");
    expect(notice.current).toBeNull();
  });

  it("says a refusal as an alert", async () => {
    const notice = useNoticeStore();
    const toast = mount(AppToast);

    notice.error("No printer is linked to this terminal");
    await toast.vm.$nextTick();

    expect(toast.find('[role="alert"]').text()).toContain("No printer is linked to this terminal");
    expect(toast.find('[role="status"]').text()).toBe("");
  });
});
