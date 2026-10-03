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
import { useAlertsStore } from "@/stores/alerts";
import { useNoticeStore } from "@/stores/notice";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

const ORDER = "RO-2026-09-00001";

vi.mock("@/api/order", () => ({
  addItem: vi.fn(),
  getOrder: vi.fn(),
  setCallName: vi.fn(),
}));

vi.mock("@/api/kitchen", () => ({
  sendToKitchen: vi.fn(),
}));

vi.mock("@/stores/alerts", () => {
  const refresh = vi.fn();
  return { useAlertsStore: () => ({ refresh }) };
});

function bill(): OrderDetail {
  return { order_name: ORDER, items: [] } as unknown as OrderDetail;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

/**
 * `D-223` — "send to the kitchen on save" was a setting nothing read. The bill is
 * saved on every add, so "save" is the moment the cashier puts it down.
 */
describe("putting a bill down", () => {
  function onType(sendOn: "manual" | "save" | "payment", status = "pending") {
    useSessionStore().data = {
      order_types: [{ name: "OT-DELIVERY", send_to_kitchen_on: sendOn }],
    } as unknown as PosSession;

    const orders = useOrderStore();
    orders.order = {
      ...bill(),
      order_type: "OT-DELIVERY",
      items: [{ idx: 1, status }],
    } as unknown as OrderDetail;
    vi.mocked(kitchenApi.sendToKitchen).mockResolvedValue({ kots_created: [], unrouted_items: [] } as never);
    vi.mocked(orderApi.getOrder).mockResolvedValue(bill());
    return orders;
  }

  it("sends what is unsent when the type sends on save", async () => {
    await onType("save").putDown();

    expect(kitchenApi.sendToKitchen).toHaveBeenCalledWith(ORDER);
  });

  it("leaves a manual type to the cashier", async () => {
    await onType("manual").putDown();

    expect(kitchenApi.sendToKitchen).not.toHaveBeenCalled();
  });

  it("sends nothing twice", async () => {
    await onType("save", "sent").putDown();

    expect(kitchenApi.sendToKitchen).not.toHaveBeenCalled();
  });
});

/**
 * `D-211` — the agent reports seconds after the send, so the store checks back.
 * What it must not do: stop before the answer lands, keep asking after it, or
 * ask about one bill once another has been opened. And once it settles, the
 * bell is asked (`D-298`) — a ticket that gave up is said there, not here.
 */
describe("a kitchen ticket on its way", () => {
  function printing(over: Partial<OrderDetail>): OrderDetail {
    return { ...bill(), tickets_printing: 0, ...over } as OrderDetail;
  }

  function sent(): ReturnType<typeof useOrderStore> {
    const orders = useOrderStore();
    orders.order = printing({ tickets_printing: 1 });
    vi.mocked(kitchenApi.sendToKitchen).mockResolvedValue({ kots_created: [], unrouted_items: [] } as never);
    return orders;
  }

  it("keeps asking while a ticket is on its way, then asks the bell and stops", async () => {
    vi.useFakeTimers();
    try {
      const orders = sent();
      vi.mocked(orderApi.getOrder)
        .mockResolvedValueOnce(printing({ tickets_printing: 1 })) // the reload after sending
        .mockResolvedValueOnce(printing({ tickets_printing: 1 })) // first check: still on its way
        .mockResolvedValueOnce(printing({ tickets_printing: 0 })); // second: settled

      await orders.sendToKitchen();

      await vi.advanceTimersByTimeAsync(5000);
      expect(useAlertsStore().refresh).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(5000);
      expect(orders.order?.tickets_printing).toBe(0);
      expect(useAlertsStore().refresh).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(60000);
      expect(orderApi.getOrder).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not keep asking about a bill once another is opened", async () => {
    vi.useFakeTimers();
    try {
      const orders = sent();
      vi.mocked(orderApi.getOrder).mockResolvedValueOnce(printing({ tickets_printing: 1 }));

      await orders.sendToKitchen();
      orders.order = { ...printing({}), order_name: "RO-2026-09-00002" };

      await vi.advanceTimersByTimeAsync(5000);

      expect(orderApi.getOrder).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("says a dish no station takes once, as a notice, not a banner", async () => {
    const orders = sent();
    vi.mocked(kitchenApi.sendToKitchen).mockResolvedValue({ kots_created: [], unrouted_items: ["Fanta"] } as never);
    vi.mocked(orderApi.getOrder).mockResolvedValue(printing({}));

    await orders.sendToKitchen();

    expect(useNoticeStore().current?.kind).toBe("info");
    expect(useNoticeStore().current?.text).toContain("Fanta");
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
