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

function bill(): OrderDetail {
  return { order_name: ORDER, items: [] } as unknown as OrderDetail;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
});

describe("one action at a time", () => {
  it("refuses a second action while the first is in flight, and says why", async () => {
    const orders = useOrderStore();
    orders.order = bill();

    // Held open on purpose: this is the window `create` used to set the order
    // from inside, which is how a watcher's `addItem` landed in it (`D-127`).
    let land!: (value: unknown) => void;
    vi.mocked(orderApi.addItem).mockReturnValue(
      new Promise((resolve) => {
        land = resolve;
      }) as ReturnType<typeof orderApi.addItem>,
    );

    const inFlight = orders.addItem("RPOS-BURGER");
    const refused = await orders.setCallName("سعيد");

    expect(refused).toBe(false);
    expect(orderApi.setCallName).not.toHaveBeenCalled();
    expect(orders.error).toBe(t("order.busy"));

    land(null);
    await inFlight;
  });

  it("takes the next action once the first has landed", async () => {
    const orders = useOrderStore();
    orders.order = bill();

    vi.mocked(orderApi.addItem).mockResolvedValue(null as never);
    vi.mocked(orderApi.getOrder).mockResolvedValue(bill());
    vi.mocked(orderApi.setCallName).mockResolvedValue(null as never);

    await orders.addItem("RPOS-BURGER");
    const accepted = await orders.setCallName("سعيد");

    expect(accepted).toBe(true);
    expect(orderApi.setCallName).toHaveBeenCalledOnce();
  });
});
