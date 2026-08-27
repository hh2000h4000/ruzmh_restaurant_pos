import { defineStore } from "pinia";
import { computed, ref } from "vue";

import * as kitchenApi from "@/api/kitchen";
import * as orderApi from "@/api/order";
import type { ModifierChoice, OrderDetail, OrderSummary } from "@/api/order";
import { isQueued } from "@/offline/queue";
import { useConnectionStore } from "@/stores/connection";

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
    await run(async () => {
      order.value = await orderApi.getOrder(orderName);
      // Whatever the server just handed back is the truth; anything this screen
      // was holding is either applied or gone.
      pendingSync.value = false;
    });
  }

  async function create(payload: Parameters<typeof orderApi.createOrder>[0]): Promise<string | null> {
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

  /** FR-2.2 — the server decides the new amount; the screen re-reads it. */
  async function setQty(idx: number, qty: number): Promise<void> {
    if (!order.value) return;

    const orderName = order.value.order_name;
    const done = await run(() => orderApi.setItemQty({ order_name: orderName, item_idx: idx, qty }));
    if (done) await open(orderName);
  }

  async function voidLine(idx: number, reason: string): Promise<void> {
    if (!order.value) return;

    const orderName = order.value.order_name;
    const done = await run(() =>
      orderApi.voidItem({ order_name: orderName, item_idx: idx, reason }),
    );
    if (done) await open(orderName);
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

  function clear(): void {
    order.value = null;
    error.value = null;
    unrouted.value = [];
    pendingSync.value = false;
  }

  return {
    order,
    busy,
    error,
    unrouted,
    pendingSync,
    lines,
    voided,
    isEmpty,
    hasUnsent,
    isClosed,
    open,
    create,
    addItem,
    setQty,
    voidLine,
    cancel,
    sendToKitchen,
    clear,
  };
});
