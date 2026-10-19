// @vitest-environment jsdom

/**
 * Closing a drawer is a blind count (`D-360`).
 *
 * The count used to open filled with what the drawer should hold, so a cashier
 * could close it without counting — the simulated shift did. What would give
 * the answer away stays hidden until the cashier says they have counted.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShiftReport } from "@/api/shift";
import CloseTillDialog from "@/components/shift/CloseTillDialog.vue";
import TillCount from "@/components/shift/TillCount.vue";
import { useShiftStore } from "@/stores/shift";

const EXPECTED = 247.9;

function summary(): ShiftReport {
  return {
    orders: { total: 7, closed: 7, cancelled: 0, still_open: 0 },
    sales: 217.4,
    by_cashier: [],
    by_method: [{ method: "Cash", kind: "till", expected: EXPECTED, sales: 197.4 }],
  } as unknown as ShiftReport;
}

async function dialog(settlementRequired = true) {
  const shift = useShiftStore();
  shift.tillSummary = vi.fn().mockResolvedValue(summary());
  shift.closeTill = vi.fn().mockResolvedValue(true);

  const wrapper = mount(CloseTillDialog, {
    props: { open: false, settlementRequired },
    global: { stubs: { teleport: true } },
  });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return { wrapper, shift };
}

const button = (wrapper: Awaited<ReturnType<typeof dialog>>["wrapper"], label: string) =>
  wrapper.findAll("button").find((b) => b.text().trim() === label)!;

beforeEach(() => setActivePinia(createPinia()));

describe("counting a drawer out", () => {
  it("starts empty, with nothing that gives the figure away", async () => {
    const { wrapper } = await dialog();

    expect(wrapper.text()).not.toContain("247.90");
    expect(wrapper.text()).not.toContain("217.40");
    expect(wrapper.find("[data-blind]").exists()).toBe(true);
    expect(button(wrapper, "خلّصت العدّ")).toBeTruthy();
  });

  it("shows the difference only once the count is done, and asks why", async () => {
    const { wrapper, shift } = await dialog();
    wrapper.findComponent(TillCount).vm.$emit("update", "Cash", "247");
    await button(wrapper, "خلّصت العدّ").trigger("click");

    expect(wrapper.text()).toContain("247.90");
    expect(wrapper.text()).toContain("-0.90");
    const close = button(wrapper, "إقفال الدرج");
    expect(close.attributes("disabled")).toBeDefined();

    await wrapper.find("input[type=text]").setValue("short by ninety halalas");
    await button(wrapper, "إقفال الدرج").trigger("click");
    await flushPromises();
    expect(shift.closeTill).toHaveBeenCalledWith({ Cash: 247 }, "short by ninety halalas");
  });

  it("hides it all again to count again", async () => {
    const { wrapper } = await dialog();
    wrapper.findComponent(TillCount).vm.$emit("update", "Cash", "200");
    await button(wrapper, "خلّصت العدّ").trigger("click");
    await button(wrapper, "أعد العدّ").trigger("click");

    expect(wrapper.text()).not.toContain("247.90");
    expect(wrapper.find("[data-blind]").exists()).toBe(true);
  });

  it("is not blind on a terminal that does not reconcile — there is nothing to count", async () => {
    const { wrapper } = await dialog(false);

    expect(wrapper.text()).toContain("247.90");
    expect(wrapper.find("[data-blind]").exists()).toBe(false);
  });
});
