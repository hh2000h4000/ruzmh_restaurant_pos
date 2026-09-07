// @vitest-environment jsdom

/**
 * What the till says about a bill still open at closing time (`D-156`).
 *
 * The branch decides whether the day may end over one (`D-105`) — and the
 * screen used to ignore that entirely: it drew *"close the day anyway"* beside
 * the count for whoever was standing there, and `can_close_shift` ships **on**
 * for a plain cashier. So the branch could set the rule and any cashier could
 * tick past it.
 *
 * The server refuses now whatever this draws (`06_git_testing_rules.md` — the
 * screen is never the authority). What these hold to is the other half: **each
 * of the three cases says something a cashier can act on** (`D-074`). A
 * disabled button with nothing beside it is the report nobody can read.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShiftReport } from "@/api/shift";
import CloseDayDialog from "@/components/shift/CloseDayDialog.vue";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";
import type { PosSession } from "@/types/session";

const OPEN_BILLS = 3;

function report(extra: Partial<ShiftReport> = {}): ShiftReport {
  return {
    shift: "SHIFT-0001",
    branch: "Riyadh",
    status: "open",
    orders: { total: 9, closed: 6, cancelled: 0, still_open: OPEN_BILLS },
    by_order_type: [],
    by_method: [],
    voids: 0,
    sales: 0,
    discounts: 0,
    till_expected: 0,
    credit_total: 0,
    ...extra,
  } as ShiftReport;
}

/** Mount the dialog for a reader with (or without) the override. */
async function open(options: { may: boolean; summary: ShiftReport }) {
  useSessionStore().data = {
    permissions: { can_close_day_with_open_orders: options.may ? 1 : 0 },
  } as unknown as PosSession;

  const shift = useShiftStore();
  shift.daySummary = vi.fn().mockResolvedValue(options.summary);

  // Mounted closed and then opened, the way the till holds it: the report is
  // fetched when `open` *changes*, so a dialog mounted already open would sit
  // on its loading line for ever and every assertion below would find nothing.
  const wrapper = mount(CloseDayDialog, {
    props: { open: false },
    global: { stubs: { teleport: true } },
  });
  await wrapper.setProps({ open: true });
  await flushPromises();

  return { wrapper, shift };
}

type Wrapper = Awaited<ReturnType<typeof open>>["wrapper"];

/** The button that ends the day is the last one in the dialog. */
const closeButton = (wrapper: Wrapper) => wrapper.findAll("button").at(-1)!;

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("closing the day over bills still open", () => {
  it("does not offer a cashier a way past the rule", async () => {
    const { wrapper } = await open({ may: false, summary: report() });

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
    expect(closeButton(wrapper).attributes("disabled")).toBeDefined();
  });

  it("tells the cashier what to do instead", async () => {
    const { wrapper } = await open({ may: false, summary: report() });

    // Not merely "3 orders are still open" — the sentence has to name the way
    // out, because for this reader there is no control that offers one.
    expect(wrapper.find('[role="status"]').text()).toContain("أقفلها أو ألغِها");
  });

  it("offers the override to whoever holds it", async () => {
    const { wrapper } = await open({ may: true, summary: report() });

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true);
    expect(closeButton(wrapper).attributes("disabled")).toBeDefined();
  });

  it("and closes on it once it is ticked", async () => {
    const { wrapper, shift } = await open({ may: true, summary: report() });
    shift.closeDay = vi.fn().mockResolvedValue(true);

    await wrapper.find('input[type="checkbox"]').setValue(true);
    expect(closeButton(wrapper).attributes("disabled")).toBeUndefined();

    await closeButton(wrapper).trigger("click");
    await flushPromises();

    expect(shift.closeDay).toHaveBeenCalledWith(true);
  });

  it("lets a cashier close where the branch carries bills over", async () => {
    const { wrapper } = await open({
      may: false,
      summary: report({ must_finish_orders: false, blocked_by_open_orders: false }),
    });

    expect(closeButton(wrapper).attributes("disabled")).toBeUndefined();
    // And says where the bills went, so nobody thinks the till lost them.
    expect(wrapper.find('[role="status"]').text()).toContain("تنتقل إلى اليوم التالي");
  });

  /**
   * `D-158` — the pile is mentioned to the person ending the day, and the day
   * still closes. A ceiling stood here for an hour: refusing an accounting act
   * because a list has grown strands a manager at two in the morning over
   * something recoverable at any time.
   */
  it("says the pile is growing without standing in the way", async () => {
    const { wrapper } = await open({
      may: false,
      summary: report({
        orders: { total: 9, closed: 6, cancelled: 0, still_open: 312 },
        must_finish_orders: false,
        blocked_by_open_orders: false,
        carrying_too_many: true,
        carry_over_warning_at: 100,
      }),
    });

    expect(wrapper.find('[role="status"]').text()).toContain("312");
    expect(closeButton(wrapper).attributes("disabled")).toBeUndefined();
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false);
  });

  it("treats a report that could not say as the stricter answer", async () => {
    // An older server, or a summary that never carried the flags: the screen
    // must not invent permission it was not given.
    const { wrapper } = await open({ may: false, summary: report() });

    expect(closeButton(wrapper).attributes("disabled")).toBeDefined();
  });

  it("takes the server's answer rather than working it out again", async () => {
    // The two branch settings live on the server and the endpoint enforces
    // them; a screen that re-derived the rule would be the copy that disagrees
    // with the refusal. Here the bills are open and the server says they are
    // not in the way — the screen believes it.
    const { wrapper } = await open({
      may: false,
      summary: report({ must_finish_orders: true, blocked_by_open_orders: false }),
    });

    expect(closeButton(wrapper).attributes("disabled")).toBeUndefined();
  });
});
