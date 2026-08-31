import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { newQueueId } from "@/api/client";
import * as kitchenApi from "@/api/kitchen";
import * as orderApi from "@/api/order";
import type { ModifierChoice, OrderDetail, OrderSummary } from "@/api/order";
import { t } from "@/i18n";
import * as local from "@/offline/localOrder";
import { isQueued } from "@/offline/queue";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The order the cashier is working on.
 *
 * Totals are never computed here. Every mutation returns the server's figures
 * and they replace what is on screen, so the number the customer is told is the
 * number the invoice will carry (`CLAUDE.md` §5.1, D-018).
 */
export const useOrderStore = defineStore("order", () => {
  const order = ref<OrderDetail | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);
  /** Set after a send, so the screen can warn about items no station received. */
  const unrouted = ref<string[]>([]);
  /**
   * An action for this order is sitting in the offline queue.
   *
   * The screen has to say so. Without it the cashier reads "cancelled" and
   * walks away, while the order is still open on the server until the queue
   * drains (09 §10, "PENDING SYNC").
   */
  const pendingSync = ref(false);

  /**
   * The bill this device is composing while the line is down (D-073).
   *
   * `null` whenever the order in hand belongs to the server, which is every
   * ordinary minute. When it is set, `order` is built from it rather than
   * fetched — the screens cannot tell, and must not have to.
   */
  const offline = ref<local.LocalOrderState | null>(null);

  /** The arithmetic's inputs, shipped by the server (D-071). Never guessed. */
  function pricing() {
    const shipped = useSessionStore().data?.pricing;
    if (!shipped) {
      // A terminal that has never loaded a session has no rate, no rounding
      // step and no method — and inventing them is precisely what D-071 exists
      // to prevent. Better to refuse the sale than to price it wrongly.
      throw new Error(t("offline.noPricing"));
    }
    return shipped;
  }

  /** Rebuild what the screens read from the local bill. */
  async function applyLocal(): Promise<void> {
    if (!offline.value) return;

    order.value = local.toOrderDetail(offline.value, pricing());
    await local.save(offline.value);
  }

  const lines = computed(() => order.value?.items.filter((row) => row.status !== "void") ?? []);
  const voided = computed(() => order.value?.items.filter((row) => row.status === "void") ?? []);
  const isEmpty = computed(() => lines.value.length === 0);
  const hasUnsent = computed(() => lines.value.some((row) => row.status === "pending"));
  const isClosed = computed(
    () => order.value?.status === "closed" || order.value?.status === "cancelled",
  );

  /** Apply the totals a write returned without re-fetching the whole order. */
  function applySummary(summary: OrderSummary): void {
    if (!order.value) return;
    order.value.status = summary.status;
    order.value.subtotal = summary.subtotal;
    order.value.discount_amount = summary.discount_amount;
    order.value.tax_amount = summary.tax_amount;
    order.value.total_amount = summary.total_amount;
  }

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    if (busy.value) return null;

    busy.value = true;
    error.value = null;
    try {
      return await action();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    } finally {
      busy.value = false;
    }
  }

  async function open(orderName: string): Promise<void> {
    // A bill this device composed lives here, not on the server (D-073).
    if (local.isLocalOrder(orderName)) {
      await run(async () => {
        offline.value = await local.load(orderName);
        if (!offline.value) throw new Error("That offline order is no longer on this device.");
        await applyLocal();
        pendingSync.value = false;
      });
      return;
    }

    await run(async () => {
      offline.value = null;
      order.value = await orderApi.getOrder(orderName);
      // Whatever the server just handed back is the truth; anything this screen
      // was holding is either applied or gone.
      pendingSync.value = false;
    });
  }

  /**
   * Open an order — on the server when there is one, on the device when there
   * is not (09 §5, D-073).
   *
   * The offline branch is not a fallback after a failed request: a till that
   * tries the network first makes every tap wait out a timeout during an
   * outage. The connection state is already known and polled (`09` §2).
   */
  async function create(payload: Parameters<typeof orderApi.createOrder>[0]): Promise<string | null> {
    if (!useConnectionStore().isOnline) {
      return run(async () => {
        offline.value = local.newLocalOrder(payload.order_type, newQueueId());
        offline.value.table = payload.table ?? null;
        offline.value.customer = payload.customer ?? null;
        offline.value.cover_count = payload.cover_count ?? 0;
        await applyLocal();
        return offline.value!.local_id;
      });
    }

    const summary = await run(() => orderApi.createOrder(payload));
    if (!summary) return null;

    await open(summary.order_name);
    return summary.order_name;
  }

  async function addItem(
    item: string,
    options: { qty?: number; modifiers?: ModifierChoice[]; notes?: string | null } = {},
  ): Promise<void> {
    if (!order.value) return;

    if (offline.value) {
      await run(async () => {
        const session = useSessionStore();
        const catalogue = session.itemsByCode.get(item);
        if (!catalogue) throw new Error(t("offline.itemUnknown"));

        // D-073 — the modifier dialog reads its options from the server, so
        // offline there is no price for "extra cheese" and no honest way to
        // invent one. The screen refuses these before the tap gets here; this
        // is the guard behind that guard.
        if (catalogue.modifier_groups.length) throw new Error(t("offline.noModifiers"));

        offline.value!.lines.push({
          item,
          item_name: catalogue.item_name,
          // The rate this device cached for the terminal's price list. The
          // server re-reads it on sync and refuses a bill that disagrees.
          rate: session.priceOf(catalogue, orderTypeOf()) ?? 0,
          qty: options.qty ?? 1,
          modifiers: [],
          notes: options.notes ?? null,
        });
        await applyLocal();
      });
      return;
    }

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.addItem({
        order_name: orderName,
        item,
        qty: options.qty ?? 1,
        modifiers: options.modifiers,
        notes: options.notes ?? null,
      }),
    );

    // The line list changed shape, so re-read rather than patch it locally.
    if (done) await open(orderName);
  }

  /** The order type in hand, for pricing a line the way the till would. */
  function orderTypeOf() {
    const session = useSessionStore();
    return session.orderTypes.find((type) => type.name === order.value?.order_type) ?? null;
  }

  /** FR-2.2 — the server decides the new amount; the screen re-reads it. */
  async function setQty(idx: number, qty: number): Promise<void> {
    if (!order.value) return;

    if (offline.value) {
      await run(async () => {
        const line = offline.value!.lines[idx - 1];
        if (line) line.qty = qty;
        await applyLocal();
      });
      return;
    }

    const orderName = order.value.order_name;
    const done = await run(() => orderApi.setItemQty({ order_name: orderName, item_idx: idx, qty }));
    if (done) await open(orderName);
  }

  /**
   * FR-2.5 — take a line off before the kitchen has it.
   *
   * The screen decides which of the two to call from `line.status`, because
   * only one of them asks the cashier a question.
   */
  async function removeLine(idx: number): Promise<void> {
    if (!order.value) return;

    if (offline.value) {
      await run(async () => {
        offline.value!.lines.splice(idx - 1, 1);
        await applyLocal();
      });
      return;
    }

    const orderName = order.value.order_name;
    const done = await run(() => orderApi.removeItem({ order_name: orderName, item_idx: idx }));
    if (done) await open(orderName);
  }

  /** FR-2.11 — a name to shout, not a Customer. */
  async function setCallName(callName: string | null): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.setCallName({ order_name: orderName, call_name: callName }),
    );

    if (!done) return false;
    await open(orderName);
    return true;
  }

  /**
   * FR-2.1 step 4 — who the bill is for, and where it goes.
   *
   * Re-read afterwards rather than patched: the customer carries a name, a
   * number and an address the bill shows, and `applySummary` only knows about
   * totals.
   */
  async function setCustomer(
    customer: string | null,
    deliveryAddress: string | null = null,
  ): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.setOrderCustomer({
        order_name: orderName,
        customer,
        delivery_address: deliveryAddress,
      }),
    );

    if (!done) return false;
    await open(orderName);
    return true;
  }

  async function voidLine(idx: number, reason: string): Promise<void> {
    if (!order.value) return;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.voidItem({ order_name: orderName, item_idx: idx, reason }),
    );
    if (done) await open(orderName);
  }

  /**
   * Turn this order into another type (D-038).
   *
   * The whole order is re-read afterwards: the price list may differ, so every
   * line's rate can have moved, and patching the totals alone would leave the
   * lines showing yesterday's prices under today's figure.
   */
  async function changeType(
    orderType: string,
    options: { table?: string | null; coverCount?: number | null } = {},
  ): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.changeOrderType({
        order_name: orderName,
        order_type: orderType,
        table: options.table ?? null,
        cover_count: options.coverCount ?? null,
      }),
    );

    if (!done) return false;
    await open(orderName);
    return true;
  }

  /**
   * Seat this order at a table, or move it to another (BR-061).
   *
   * Re-read afterwards: the hall follows the table (D-040) and the guest count
   * may have been filled in from its capacity, so more changed than the totals.
   */
  async function seat(table: string, coverCount?: number | null): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.setOrderTable({
        order_name: orderName,
        table,
        cover_count: coverCount ?? null,
      }),
    );

    if (!done) return false;
    await open(orderName);
    return true;
  }

  /** FR-2.9 — one line's note. Any item, and after the kitchen has it. */
  async function setLineNotes(idx: number, notes: string | null): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.setItemNotes({ order_name: orderName, item_idx: idx, notes }),
    );

    if (!done) return false;
    await open(orderName);
    return true;
  }

  /** FR-2.9 — the note every station reads. */
  async function setNotes(notes: string | null): Promise<boolean> {
    if (!order.value) return false;

    const orderName = order.value.order_name;
    const done = await run(() => orderApi.setOrderNotes({ order_name: orderName, notes }));

    if (!done) return false;
    await open(orderName);
    return true;
  }

  async function cancel(reason: string): Promise<boolean> {
    if (!order.value) return false;

    const done = await run(() =>
      orderApi.cancelOrder({ order_name: order.value!.order_name, reason }),
    );
    if (!done) return false;

    if (isQueued(done)) {
      pendingSync.value = true;
      void useConnectionStore().refreshCounts();
    } else {
      applySummary(done);
    }
    return true;
  }

  async function sendToKitchen(): Promise<boolean> {
    if (!order.value) return false;

    const result = await run(() => kitchenApi.sendToKitchen(order.value!.order_name));
    if (!result) return false;

    if (isQueued(result)) {
      // The ticket is held on this device. Nothing has reached a station, so
      // the lines stay as they are and the screen says why.
      pendingSync.value = true;
      void useConnectionStore().refreshCounts();
      return true;
    }

    unrouted.value = result.unrouted_items;
    await open(order.value.order_name);
    return true;
  }

  /**
   * Take money for a bill this device composed (09 §5, D-073).
   *
   * The whole thing goes into the queue as one entry, under the id it was built
   * with — so the queue's ordinary replay is what lands it, and the ordinary
   * idempotency is what stops it landing twice (`D-072`). There is no second
   * sync path here to drift from the first.
   *
   * The local copy is dropped once it is queued: a paid bill with two homes
   * would make the screen choose which one is true.
   */
  async function payOffline(
    payments: { method: string; amount: number; tendered?: number }[],
  ): Promise<boolean> {
    const state = offline.value;
    if (!state) return false;

    const done = await run(async () => {
      const { enqueue } = await import("@/offline/queue");
      await enqueue(
        "offline.submit_order",
        {
          pos_profile: useSessionStore().profile!.name,
          payload: toSubmissionPayload(state, payments),
        },
        local.queueIdOf(state),
      );
      await local.forget(state.local_id);
      return true;
    });

    if (!done) return false;

    offline.value = null;
    pendingSync.value = true;
    void useConnectionStore().refreshCounts();
    return true;
  }

  function toSubmissionPayload(
    state: local.LocalOrderState,
    payments: { method: string; amount: number; tendered?: number }[],
  ): Record<string, unknown> {
    return local.toSubmission(state, pricing(), payments);
  }

  function clear(): void {
    order.value = null;
    offline.value = null;
    error.value = null;
    unrouted.value = [];
    pendingSync.value = false;
  }

  return {
    order,
    offline,
    busy,
    error,
    unrouted,
    pendingSync,
    payOffline,
    lines,
    voided,
    isEmpty,
    hasUnsent,
    isClosed,
    open,
    create,
    addItem,
    setQty,
    changeType,
    seat,
    setNotes,
    setLineNotes,
    setCallName,
    setCustomer,
    removeLine,
    voidLine,
    cancel,
    sendToKitchen,
    clear,
  };
});
