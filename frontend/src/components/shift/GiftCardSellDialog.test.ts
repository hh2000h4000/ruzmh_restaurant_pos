// @vitest-environment jsdom

/**
 * Selling a card in two steps, one pad at a time (`D-381`).
 *
 * The card's number first, then Next; then the amount and what it was paid
 * with, then Sell. The two keypads used to sit side by side in a sheet as wide
 * as the till, and before that stacked past the screen (`D-256`).
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GiftCardSellDialog from "@/components/shift/GiftCardSellDialog.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/giftCard", () => ({ sellGiftCard: vi.fn() }));

beforeEach(() => {
  setActivePinia(createPinia());
  useSessionStore().data = {
    payment_methods: [
      { mode_of_payment: "Cash", is_credit: 0, default: 1 },
      { mode_of_payment: "Card balance", is_credit: 0, is_gift_card: 1 },
      { mode_of_payment: "Talabat", is_credit: 1 },
    ],
  } as unknown as PosSession;
});

async function sheet() {
  const wrapper = mount(GiftCardSellDialog, {
    props: { open: false },
    global: { stubs: { teleport: true } },
  });
  await wrapper.setProps({ open: true });
  await flushPromises();
  return wrapper;
}

function button(wrapper: Awaited<ReturnType<typeof sheet>>, label: string) {
  return wrapper.findAll("button").find((b) => b.text().trim() === label)!;
}

describe("selling a card", () => {
  it("asks for the number first, and moves on only with one", async () => {
    const wrapper = await sheet();

    expect(wrapper.find('[data-step="number"]').exists()).toBe(true);
    expect(wrapper.find('[data-step="amount"]').exists()).toBe(false);
    expect(button(wrapper, "التالي").attributes("disabled")).toBeDefined();

    await wrapper.find("input").setValue("gc-1001");
    await button(wrapper, "التالي").trigger("click");

    expect(wrapper.find('[data-step="amount"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("GC-1001");
  });

  it("offers only what puts money in the drawer to pay for a card", async () => {
    // `D-276` — a card bought with a card held a balance nobody paid for.
    const wrapper = await sheet();
    await wrapper.find("input").setValue("GC-1");
    await button(wrapper, "التالي").trigger("click");

    const labels = wrapper.find('[data-step="amount"]').findAll("button").map((b) => b.text().trim());
    expect(labels).toContain("نقد");
    expect(labels).toContain("بيع");
    expect(labels).not.toContain("Card balance");
    expect(labels).not.toContain("Talabat");
  });

  it("goes back to the number without losing it", async () => {
    const wrapper = await sheet();
    await wrapper.find("input").setValue("GC-7");
    await button(wrapper, "التالي").trigger("click");
    await button(wrapper, "GC-7تغيير").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-step="number"]').exists()).toBe(true);
    expect((wrapper.find("input").element as HTMLInputElement).value).toBe("GC-7");
  });
});
