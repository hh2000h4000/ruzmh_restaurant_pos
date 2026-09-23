// @vitest-environment jsdom

/**
 * Notes in and out of the drawer, from the till (`D-245`).
 *
 * The cashier buys a bag of ice out of the till. The claims tested are the ones
 * the drawer's honesty rests on: nothing is sent without a reason, the amount
 * and the direction reach the server as typed, and a cashier who does not hold
 * the permission is asked for a manager before anything moves rather than after.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DrawerCashDialog from "@/components/shift/DrawerCashDialog.vue";
import { useSessionStore } from "@/stores/session";

const moveDrawerCash = vi.fn();
const validateManagerOverride = vi.fn();

vi.mock("@/api/shift", () => ({
  moveDrawerCash: (...args: unknown[]) => moveDrawerCash(...args),
}));
vi.mock("@/api/payment", () => ({
  validateManagerOverride: (...args: unknown[]) => validateManagerOverride(...args),
}));

const NOTES = [
  { name: "n1", title: "Bought supplies", title_ar: "شراء مستلزمات", scope: "cash_reason" },
  { name: "n2", title: "No onion", title_ar: "بدون بصل", scope: "item" },
];

function dialog(allowed: boolean) {
  const session = useSessionStore();
  session.data = {
    quick_notes: NOTES,
    pos_profile: { name: "Till 1" },
    permissions: { can_move_drawer_cash: allowed ? 1 : 0 },
  } as never;

  return mount(DrawerCashDialog, {
    props: { open: true },
    global: { stubs: { teleport: true } },
  });
}

/** Tap a figure into the keypad, then the confirming button by its text. */
async function type(view: ReturnType<typeof dialog>, digits: string) {
  for (const digit of digits) {
    const key = view.findAll("button").find((button) => button.text().trim() === digit);
    if (key) await key.trigger("click");
  }
}

/**
 * Tap a button by its words.
 *
 * `last` picks the one furthest down the tree, which is how the reason sheet's
 * own confirm is reached: it stacks over the dialog and both say the same word.
 */
async function tap(view: ReturnType<typeof dialog>, text: string, last = false) {
  const matches = view.findAll("button").filter((one) => one.text().trim() === text);
  expect(matches.length, `no button reading "${text}"`).toBeGreaterThan(0);
  await matches[last ? matches.length - 1 : 0].trigger("click");
  await flushPromises();
}

describe("moving notes in and out of the drawer", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    moveDrawerCash.mockReset();
    moveDrawerCash.mockResolvedValue({ movement: "CASH-0001" });
    validateManagerOverride.mockReset();
    validateManagerOverride.mockResolvedValue({ override_token: "tok" });
  });

  it("sends nothing until a reason has been given", async () => {
    const view = dialog(true);

    await type(view, "30");
    await tap(view, "سجّلها");

    expect(moveDrawerCash).not.toHaveBeenCalled();
  });

  it("sends the amount and the direction as they were typed", async () => {
    const view = dialog(true);

    await type(view, "30");
    await tap(view, "سجّلها");
    await tap(view, "شراء مستلزمات");
    await tap(view, "سجّلها", true);

    expect(moveDrawerCash).toHaveBeenCalledWith(
      expect.objectContaining({ direction: "out", amount: 30, reason: "شراء مستلزمات" }),
    );
  });

  it("asks a manager first when the cashier may not do it alone", async () => {
    const view = dialog(false);

    await type(view, "10");
    await tap(view, "سجّلها");
    await tap(view, "شراء مستلزمات");
    await tap(view, "سجّلها", true);

    expect(moveDrawerCash).not.toHaveBeenCalled();
    expect(view.text()).toContain("يحتاج مدير");
  });

  it("shows the server's refusal rather than a guess of its own", async () => {
    moveDrawerCash.mockRejectedValue(new Error("Open a shift before taking orders."));
    const view = dialog(true);

    await type(view, "10");
    await tap(view, "سجّلها");
    await tap(view, "شراء مستلزمات");
    await tap(view, "سجّلها", true);

    expect(view.text()).toContain("Open a shift");
  });
});
