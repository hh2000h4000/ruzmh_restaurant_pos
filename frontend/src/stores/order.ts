import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { newQueueId } from "@/api/client";
import * as kitchenApi from "@/api/kitchen";
import * as orderApi from "@/api/order";
import type { ModifierChoice, OrderDetail, OrderSummary } from "@/api/order";
import { t } from "@/i18n";
import * as local from "@/offline/localOrder";
import { isQueued } from "@/offline/queue";
import { useAlertsStore } from "@/stores/alerts";
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
  /**
   * An action for this order is sitting in the offline queue.
   *
   * The screen has to say so. Without it the cashier reads "cancelled" and
   * walks away, while the order is still open on the server until the queue
   * drains (09 §10, "PENDING SYNC").
   */
  const pendingSync = ref(false);

  /**
   * Bumped whenever a call through `run` **settles** — succeeded or refused
   * (`D-180`, amended by `D-181`).
   *
   * **The floor list has no other way to know.** It polls every fifteen
   * seconds, so a bill this cashier had just cancelled sat on their own screen
   * until the next tick — the user watched a row they had killed linger for
   * seconds. Polling answers "what did the *other* terminals do"; it is the
   * wrong instrument for "what did I just do", and no interval short enough to
   * hide that is one a till should be running.
   *
   * **On refusal too, and that is the whole of `D-181`.** It fired on success
   * only at first, on the reasoning that a refused action changed nothing. It
   * changed nothing *on the server* — but a refusal is the strongest evidence
   * there is that **this screen** is wrong: "that order is already cancelled"
   * means somebody else ended it and we are still drawing it. So the moment we
   * are told we were mistaken is the moment to ask again. TanStack Query
   * settled on the same rule and names it in one line — *always refetch after
   * error or success* — which is why its invalidation goes in `onSettled`.
   *
   * A counter rather than a call at each site: there are eighteen mutations
   * here and the nineteenth is the one somebody forgets (`CLAUDE.md` §5.5).
   * `run` is the door every one of them already goes through.
   *
   * It bumps on reads too — `open` uses `run` as well — and that is left alone
   * deliberately. Opening a bill is a moment the floor list is worth having
   * right, the listener coalesces anyway, and a flag at each call site to tell
   * the two apart is the per-site memory this exists to avoid.
   */
  const settledAt = ref(0);

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
    order.value.promotion_amount = summary.promotion_amount;
    order.value.promotion_title = summary.promotion_title;
    order.value.promotion_title_ar = summary.promotion_title_ar;
    order.value.tax_amount = summary.tax_amount;
    order.value.total_amount = summary.total_amount;
  }

  /**
   * One action at a time, and **it says so when it refuses** (`D-128`).
   *
   * `null` from here means one of two things — it failed, or it never started —
   * and both set `error`, because every caller renders `error` and none of them
   * can tell the two apart. It used to return `null` silently on the second
   * count: `TablesView` then assigned that empty `error` to its own failure
   * line and cleared the cashier's table with **nothing on the screen at all**,
   * which is the worst report a till can give (`D-074`).
   *
   * **The refusal itself stays.** Queueing the second action instead would run
   * it against a list that moved: `setQty`, `removeLine`, `voidLine` and
   * `setLineNotes` all address a line by `idx`, and Frappe renumbers `idx` when
   * a row is removed — so a queued call would edit the wrong dish. Dropping is
   * the safe half of this contract; the silence was the unsafe half.
   *
   * A cashier rarely meets it: every control that calls a mutation is disabled
   * while `busy` (`OrderView`'s `locked`). What it really guards against is a
   * **programmatic** caller — a watcher, a route change, a timer — which is
   * where it has actually bitten (`D-127`).
   */
  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    if (busy.value) {
      error.value = t("order.busy");
      return null;
    }

    busy.value = true;
    error.value = null;
    try {
      return await action();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    } finally {
      busy.value = false;
      // In `finally`, so it fires on the refusal as well. The early return
      // above — the one that turns a re-entrant call away — is outside this
      // block on purpose: nothing was attempted there, so nothing settled.
      settledAt.value += 1;
    }
  }

  async function open(orderName: string): Promise<void> {
    // A bill this device composed lives here, not on the server (D-073).
    if (local.isLocalOrder(orderName)) {
      await run(async () => {
        const state = await local.load(orderName);
        if (!state) throw new Error(t("offline.billGone"));

        // Rendered *before* it is adopted. `applyLocal` needs the pricing the
        // server shipped, and a terminal whose cached session predates it has
        // none — assigning first would leave `offline` set with no `order`
        // beside it, which every screen reads as "an offline bill" and then
        // finds nothing to draw.
        order.value = local.toOrderDetail(state, pricing());
        offline.value = state;
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
    options: { qty?: number; modifiers?: ModifierChoice[]; notes?: string | null; rate?: number } = {},
  ): Promise<void> {
    if (!order.value) return;

    if (offline.value) {
      await run(async () => {
        const session = useSessionStore();
        const catalogue = session.itemsByCode.get(item);
        if (!catalogue) throw new Error(t("offline.itemUnknown"));

        offline.value!.lines.push({
          item,
          item_name: catalogue.item_name,
          // The rate this device cached for the terminal's price list. The
          // server re-reads it on sync and refuses a bill that disagrees —
          // except a price typed at the counter, which it takes from the line.
          rate: options.rate ?? session.priceOf(catalogue, orderTypeOf()) ?? 0,
          qty: options.qty ?? 1,
          modifiers: resolveModifiers(options.modifiers),
          notes: options.notes ?? null,
          open_price: options.rate !== undefined,
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
        rate: options.rate,
      }),
    );

    // The line list changed shape, so re-read rather than patch it locally.
    if (done) await open(orderName);
  }

  /**
   * Price the chosen options from the groups the session shipped (D-076).
   *
   * Display money, not authority: `add_item` prices every option again from
   * `POS Modifier Option` (`D-020`), and the offline replay refuses a bill whose
   * total disagrees with the server's (`D-072`). What this buys is a cashier who
   * can sell "extra cheese" during an outage and a customer who is quoted the
   * right figure.
   */
  function resolveModifiers(chosen: ModifierChoice[] | undefined) {
    if (!chosen?.length) return [];

    const groups = useSessionStore().data?.modifier_groups ?? [];

    return chosen.flatMap((choice) => {
      const group = groups.find((row) => row.name === choice.group);
      const option = group?.options.find((row) => row.title === choice.option);
      if (!group || !option) return [];

      // `amount` is the option's own price and `price_effect` says which way it
      // pulls — the shape `utils/order._resolve_modifiers` stores, so a line
      // reads the same whether it was built here or came back from the server.
      return [
        {
          group: group.name,
          option: option.title,
          option_ar: option.title_ar || option.title,
          amount: option.price_amount,
          price_effect: option.price_effect,
        },
      ];
    });
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

  /**
   * How often, and how many times, the screen checks back on tickets still on
   * their way to a printer (`D-211`). Thirty seconds covers an agent's poll and
   * a printer's three tries of five seconds.
   */
  const PRINT_CHECK_MS = 5000;
  const PRINT_CHECKS = 6;
  /** Bumped by each new watch, so an older one stops rather than racing it. */
  let printWatch = 0;

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

    const name = order.value.order_name;
    await open(name);
    void followPrinting(name);
    return true;
  }

  /**
   * Put the bill down, and send what is unsent when its type says so (`D-223`).
   *
   * `send_to_kitchen_on = save` was a setting nothing read: every type on it —
   * the shipped Delivery and the delivery apps among them — behaved as manual.
   * "Save" here is the moment the cashier leaves the bill: a new order, or
   * another one opened. Every add is already saved to the server, so sending on
   * each one would print a ticket per tap. Paying straight from the bill is the
   * server's half (`payment._send_kitchen_if_due`).
   */
  async function putDown(): Promise<void> {
    const current = order.value;
    if (!current || !hasUnsent.value) return;

    const type = useSessionStore().orderTypes.find((row) => row.name === current.order_type);
    if (type?.send_to_kitchen_on !== "save") return;

    await sendToKitchen();
  }

  /**
   * Check back while tickets are on their way to a printer (`D-211`).
   *
   * The answer is not in the send's reply: the agent reports seconds later, and
   * a printer that is off takes three tries of five seconds to give up. So the
   * screen asks again a few times and stops as soon as nothing is still printing
   * — after that, whatever the cashier does next reloads the order anyway.
   *
   * **And when it stops, the bell asks** (`D-298`): a ticket that gave up is the
   * bell's to say now, not a banner on this bill.
   *
   * **Not through `run`.** A timer is exactly the programmatic caller `run`
   * turns away with "still busy" (`D-128`). And it only reads: it copies the one
   * print field and nothing else, so a line the cashier is editing is never
   * overwritten by an older copy of the bill.
   */
  async function followPrinting(orderName: string): Promise<void> {
    const watch = ++printWatch;

    for (let check = 0; check < PRINT_CHECKS; check += 1) {
      if (!order.value?.tickets_printing) return;

      await new Promise((resolve) => setTimeout(resolve, PRINT_CHECK_MS));
      if (watch !== printWatch || order.value?.order_name !== orderName) return;

      try {
        const fresh = await orderApi.getOrder(orderName);
        if (watch !== printWatch || order.value?.order_name !== orderName) return;
        order.value.tickets_printing = fresh.tickets_printing;
        if (!fresh.tickets_printing) void useAlertsStore().refresh();
      } catch {
        // The next action reloads the order; a missed check is not worth a
        // message on the screen.
        return;
      }
    }
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
    pendingSync.value = false;
  }

  return {
    order,
    offline,
    busy,
    error,
    pendingSync,
    settledAt,
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
    putDown,
    clear,
  };
});
