/**
 * The order store's one-action-at-a-time contract (`D-128`).
 *
 * `run` refuses a second action while the first is in flight, and the refusal
 * is **correct**: `setQty`, `removeLine`, `voidLine` and `setLineNotes` all
 * address a line by `idx`, and Frappe renumbers `idx` when a row is removed, so
 * an action queued behind another would edit the wrong dish.
 *
 * What was wrong was that it refused *silently*. `null` with no `error` is
 * indistinguishable from a failure whose message somebody cleared, and
 * `TablesView` assigned that empty error to its own failure line and wiped the
 * cashier's table with nothing on the screen (`D-074`). This test is here so
 * the message cannot be dropped again by someone tidying up.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as kitchenApi from "@/api/kitchen";
import type { OrderDetail } from "@/api/order";
import * as orderApi from "@/api/order";
import { t } from "@/i18n";
import { useOrderStore } from "@/stores/order";

const ORDER = "RO-2026-09-00001";

vi.mock("@/api/order", () => ({
  addItem: vi.fn(),
  getOrder: vi.fn(),
  setCallName: vi.fn(),
}));

vi.mock("@/api/kitchen", () => ({
  reprintKot: vi.fn(),
  sendToKitchen: vi.fn(),
}));

function bill(): OrderDetail {
  return { order_name: ORDER, items: [] } as unknown as OrderDetail;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

/**
 * `D-211` — the agent reports seconds after the send, so the store checks back.
 * What it must not do: stop before the answer lands, keep asking after it, or
 * paint one bill's failure onto another the cashier has opened since.
 */
describe("a kitchen ticket that did not print", () => {
  const TICKET = { kot_name: "KOT-2026-09-00001", station: "Grill", station_ar: "الشواية" };

  function printing(over: Partial<OrderDetail>): OrderDetail {
    return { ...bill(), unprinted_tickets: [], tickets_printing: 0, ...over } as OrderDetail;
  }

  it("keeps asking while a ticket is on its way, shows the failure, then stops", async () => {
    vi.useFakeTimers();
    try {
      const orders = useOrderStore();
      orders.order = printing({ tickets_printing: 1 });
      vi.mocked(kitchenApi.reprintKot).mockResolvedValue({ kot_name: TICKET.kot_name, print_status: "pending" });
      vi.mocked(orderApi.getOrder)
        .mockResolvedValueOnce(printing({ tickets_printing: 1 })) // the reload after asking
        .mockResolvedValueOnce(printing({ tickets_printing: 1 })) // first check: still on its way
        .mockResolvedValueOnce(printing({ unprinted_tickets: [TICKET] })); // second: it gave up

      await orders.reprintTicket(TICKET.kot_name);

      await vi.advanceTimersByTimeAsync(5000);
      expect(orders.order?.unprinted_tickets).toEqual([]);

      await vi.advanceTimersByTimeAsync(5000);
      expect(orders.order?.unprinted_tickets).toEqual([TICKET]);

      await vi.advanceTimersByTimeAsync(60000);
      expect(orderApi.getOrder).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not paint one bill's ticket onto another opened since", async () => {
    vi.useFakeTimers();
    try {
      const orders = useOrderStore();
      orders.order = printing({ tickets_printing: 1 });
      vi.mocked(kitchenApi.reprintKot).mockResolvedValue({ kot_name: TICKET.kot_name, print_status: "pending" });
      vi.mocked(orderApi.getOrder)
        .mockResolvedValueOnce(printing({ tickets_printing: 1 }))
        .mockResolvedValue(printing({ unprinted_tickets: [TICKET] }));

      await orders.reprintTicket(TICKET.kot_name);
      orders.order = { ...printing({}), order_name: "RO-2026-09-00002" };

      await vi.advanceTimersByTimeAsync(5000);

      expect(orders.order?.unprinted_tickets).toEqual([]);
      expect(orderApi.getOrder).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("one action at a time", () => {
  it("refuses a second action while the first is in flight, and says why", async () => {
    const orders = useOrderStore();
    orders.order = bill();

    // Held open on purpose: this is the window `create` used to set the order
    // from inside, which is how a watcher's `addItem` landed in it (`D-127`).
    let land!: () => void;
    vi.mocked(orderApi.addItem).mockReturnValue(
      new Promise<never>((resolve) => {
        land = () => resolve(null as never);
      }),
    );

    const inFlight = orders.addItem("RPOS-BURGER");
    const refused = await orders.setCallName("سعيد");

    expect(refused).toBe(false);
    expect(orderApi.setCallName).not.toHaveBeenCalled();
    expect(orders.error).toBe(t("order.busy"));

    land();
    await inFlight;
  });

  it("takes the next action once the first has landed", async () => {
    const orders = useOrderStore();
    orders.order = bill();

    // The server answers with the recalculated totals; the store reads any
    // answer as "it happened" and a `null` as "it did not".
    const totals = {
      status: "active",
      subtotal: 0,
      discount_amount: 0,
      promotion_amount: 0,
      promotion_title: "",
      promotion_title_ar: "",
      tax_amount: 0,
      total_amount: 0,
    };
    vi.mocked(orderApi.addItem).mockResolvedValue(totals as never);
    vi.mocked(orderApi.getOrder).mockResolvedValue(bill());
    vi.mocked(orderApi.setCallName).mockResolvedValue(totals as never);

    await orders.addItem("RPOS-BURGER");
    const accepted = await orders.setCallName("سعيد");

    expect(accepted).toBe(true);
    expect(orderApi.setCallName).toHaveBeenCalledOnce();
  });
});
