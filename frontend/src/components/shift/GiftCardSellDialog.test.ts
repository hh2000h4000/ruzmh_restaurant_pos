// @vitest-environment jsdom

/**
 * The sell button stays in reach (`D-256`).
 *
 * Two keypads — letters for the card's number, digits for the amount — stacked
 * to 968 pixels on an 800-pixel till, and the button that sells sat under both.
 * The cashier had to scroll to finish a sale nobody told them was unfinished.
 *
 * jsdom lays nothing out, so this cannot measure the fold. What it can hold is
 * the shape that keeps the button above it: the answer lives in the dialog's
 * pinned footer, not at the end of the body.
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GiftCardSellDialog from "@/components/shift/GiftCardSellDialog.vue";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/giftCard", () => ({ sellGiftCard: vi.fn() }));

beforeEach(() => {
  setActivePinia(createPinia());
  useSessionStore().data = {
    payment_methods: [{ mode_of_payment: "Cash", is_credit: 0, default: 1 }],
  } as unknown as PosSession;
});

function sheet() {
  return mount(GiftCardSellDialog, {
    props: { open: true },
    global: { stubs: { teleport: true } },
  });
}

describe("selling a card", () => {
  it("keeps the sell button and the method in the pinned footer", () => {
    const footer = sheet().find('[data-dialog-footer]');

    expect(footer.exists()).toBe(true);
    const labels = footer.findAll("button").map((button) => button.text().trim());
    expect(labels).toContain("بيع");
    expect(labels).toContain("Cash");
  });

  it("asks for a wide sheet, so the two keypads can sit side by side", () => {
    const panel = sheet().find('[role="dialog"]');

    expect(panel.classes()).toContain("max-w-5xl");
  });
});
