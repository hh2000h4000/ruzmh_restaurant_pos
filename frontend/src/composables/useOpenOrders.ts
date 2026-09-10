import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import {
  countCarriedOrders,
  listOrders,
  searchOrders,
  type OpenOrder,
  type OrderView,
} from "@/api/order";
import { t } from "@/i18n";
import { recall, remember, warm } from "@/offline/orderMirror";
import { queuedSales } from "@/offline/queue";
import { useConnectionStore } from "@/stores/connection";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";

export type OrderSort = "oldest" | "newest" | "amount";
export type OrderScope = "mine" | "all";

/**
 * The floor: every order still open, kept fresh, filtered, and sorted.
 *
 * Extracted from the till screen so the order screen can show the same list in
 * a pane without a second copy of the polling, the scope rule and the sort
 * (D-039). Each caller gets its own state — two screens are never mounted at
 * once, and a shared store would have to be invalidated by hand.
 */
/**
 * When a row happened — closed if it has, opened if it has not (`D-146`).
 *
 * The same choice `OpenOrderRow` makes for the date it prints, so the list is
 * ordered by the moment it shows rather than by a different one.
 */
function happenedAt(order: OpenOrder): string {
  return order.closed_at ?? order.opened_at;
}

export function useOpenOrders() {
  const session = useSessionStore();
  const connection = useConnectionStore();

  const rows = ref<OpenOrder[]>([]);
  const error = ref<string | null>(null);
  const loading = ref(false);
  /** When these rows came from the server, if they are not fresh (D-080). */
  const staleAt = ref<string | null>(null);

  const search = ref("");
  /**
   * **Newest first, on every tab** — the user's instruction, and the reading
   * that matches what the tabs are for.
   *
   * "Oldest first" was written for the floor alone, where the bill that has
   * waited longest is the one needing attention (`06` Screen 1). It stopped
   * being right the moment the same list grew three history tabs: what a
   * cashier wants from *closed today* is the bill they just closed, and from
   * *refunds* the one just taken. The server already returns both of those
   * newest first — and this then sorted them back the other way.
   *
   * The floor keeps the old reading one tap away, in the sort itself.
   */
  const sort = ref<OrderSort>("newest");

  /** Which orders to ask for: open, today's history, refunds, or everything. */
  const view = ref<OrderView>("open");

  /**
   * Whether the open list also holds bills carried from a day that has ended.
   *
   * **Off by default, and a switch rather than a tab** (`D-168`). A carried bill
   * is an open bill — the tabs are statuses, and age is not one — so it widens
   * the list the cashier is already looking at. Off by default because the
   * ordinary list must stay one business day wide: it is pulled on every action
   * and on every terminal, and unbounded it grows with the age of the shop
   * (`D-158`, measured at four seconds for three thousand bills).
   */
  const includeCarried = ref(false);

  /** "Mine" is the default even for a supervisor: the smaller list is the calmer one. */
  const scope = ref<OrderScope>("mine");

  /**
   * `null` hides the switch entirely. The backend enforces the same rule — without
   * the right it does not return other people's orders — so this only decides
   * whether an empty tab is worth offering.
   */
  const maySeeEveryone = computed(() => session.can("can_view_all_orders"));

  /**
   * Bills sold on this device and still in the queue (D-075).
   *
   * They are not on the server, so no list of orders can contain them — and a
   * cashier who has just taken money and cannot find the bill will take it
   * again. They appear beside the real ones, marked, until the queue drains.
   */
  const queued = ref<OpenOrder[]>([]);

  async function refreshQueued(): Promise<void> {
    const user = session.data?.user ?? null;

    queued.value = (await queuedSales()).map((entry) => {
      const payload = (entry.payload.payload ?? {}) as Record<string, never>;
      const totals = (payload.totals ?? {}) as Record<string, number>;
      const lines = (payload.lines ?? []) as unknown[];
      const type = session.orderTypes.find((row) => row.name === payload.order_type);

      return {
        name: entry.queue_id,
        daily_number: 0,
        call_name: (payload.call_name as string | null) ?? null,
        order_type: (payload.order_type as string) ?? "",
        order_type_title: type?.title ?? "",
        order_type_title_ar: type?.title_ar ?? "",
        icon: type?.icon ?? null,
        color: type?.color ?? null,
        status: "queued",
        table: null,
        table_number: null,
        cover_count: 0,
        customer: null,
        cashier: user,
        cashier_name: session.data?.user_name ?? user,
        total_amount: totals.total_amount ?? 0,
        returned_amount: 0,
        opened_at: entry.created_at,
        // A queued sale is money already taken (`D-075`), so the moment that
        // matters is when it was rung up — which is the only moment it has.
        closed_at: entry.created_at,
        item_count: lines.length,
        // A sale queued on this device was rung up today, on the day this till
        // is working. Nothing about it is carried (`D-164`).
        is_carried: 0,
      } satisfies OpenOrder;
    });
  }

  /**
   * A search that reached past today, and what it found (`D-152`).
   *
   * `null` means nobody has asked. It is deliberately **not** part of the poll:
   * the tabs keep refreshing underneath, and these rows stay exactly as the
   * server answered until the cashier clears them — a result list that changed
   * on a timer would move under the hand reaching for it.
   */
  const older = ref<OpenOrder[] | null>(null);
  const searchingOlder = ref(false);

  async function searchOlder(): Promise<void> {
    const profile = session.profile?.name;
    const text = search.value.trim();
    if (!profile || !text) return;

    searchingOlder.value = true;
    error.value = null;
    try {
      older.value = await searchOrders(profile, text);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      searchingOlder.value = false;
    }
  }

  /** Any new question drops the last answer, so the two are never mixed. */
  watch([search, view, scope], () => {
    older.value = null;
  });

  const visible = computed(() => {
    // What the server found, when it was asked. Nothing is merged into it: a
    // list that is half today and half March is a list nobody can read.
    if (older.value) return older.value;

    // Only where a paid bill belongs. They are sales, so they sit with the
    // day's history, not on the open floor.
    let list =
      view.value === "closed" || view.value === "all"
        ? [...queued.value, ...rows.value]
        : rows.value;

    if (maySeeEveryone.value && scope.value === "mine") {
      list = list.filter((order) => order.cashier === session.data?.user);
    }

    const needle = search.value.trim().toLowerCase();
    if (needle) {
      // Everything somebody at the counter might quote (`D-152`). The short
      // number and the invoice number were both missing, so a customer reading
      // their own receipt out loud could not be found on the day they were served.
      list = list.filter((order) =>
        [
          order.daily_number,
          order.name,
          order.sales_invoice,
          order.credit_note,
          order.customer_name,
          order.call_name,
          order.table_number,
          order.cashier_name,
          order.order_type_title_ar,
        ]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(needle)),
      );
    }

    // A copy: sorting in place would mutate what the fetch returned and make the
    // next comparison depend on the last render.
    return [...list].sort((a, b) => {
      if (sort.value === "amount") return b.total_amount - a.total_amount;
      // **By the event the row is about** (`D-146`) — the same moment the row
      // prints under its number. Sorting closed bills by when they *opened* put
      // one opened at eleven and paid at one at the wrong end of "today", and
      // undid the order the server had already put them in.
      const direction = sort.value === "newest" ? -1 : 1;
      return direction * happenedAt(a).localeCompare(happenedAt(b));
    });
  });

  async function refresh(): Promise<void> {
    const profile = session.profile?.name;
    if (!profile) return;

    // First, and never inside the `try`: these are on this device, so they are
    // readable when the server is not — which is exactly when they exist
    // (D-075).
    await refreshQueued();

    loading.value = true;
    try {
      rows.value = await listOrders(profile, view.value, includeCarried.value);
      error.value = null;
      staleAt.value = null;
      // D-080 — so the next outage still has a day's history to show.
      await remember(view.value, rows.value);
      // **Asked separately, and it must not be able to break the list.** The
      // number on the carried tab is worth having and the floor is worth more:
      // a count that failed inside the same `try` would send a working list to
      // the outage branch (`D-164`).
      void refreshCarriedCount(profile);
    } catch (cause) {
      const mirrored = await recall(view.value);

      if (mirrored) {
        // Not an error: it is the last answer the server gave, and the screen
        // says how old it is. An outage that emptied every list is what this
        // replaces.
        rows.value = mirrored.orders;
        staleAt.value = mirrored.cached_at;
        error.value = null;
      } else {
        // The list is a convenience; a failure here must not blank the screen
        // or stop a cashier opening a new order.
        rows.value = [];
        error.value = cause instanceof Error ? cause.message : t("home.openOrdersFailed");
      }
    } finally {
      loading.value = false;
    }
  }

  /**
   * How many bills are carried, for the tab's own label (`D-164`).
   *
   * **The last known number is kept when the call fails**, rather than dropped
   * to zero. Offline, "carried (0)" is a claim the device cannot make and the
   * one reading a cashier would act on — it says the backlog is cleared.
   */
  const carriedCount = ref(0);

  async function refreshCarriedCount(profile: string): Promise<void> {
    try {
      carriedCount.value = (await countCarriedOrders(profile)).carried;
    } catch {
      // Kept as it was. The list beside it already says the screen is stale.
    }
  }

  /**
   * The poll, and **what it is now for** (`D-180`).
   *
   * Fifteen seconds answers "what have the *other* terminals done" — a bill
   * settled at the counter beside this one, a table seated by a waiter. It was
   * also, by accident, the only thing that noticed **this** cashier's own
   * actions, and that is what the user saw: a bill they had just cancelled sat
   * on their screen for seconds afterwards. Their own work now arrives through
   * `changedAt` the moment it lands, and no interval has to apologise for it.
   */
  const REFRESH_MS = 15_000;

  let timer: number | undefined;

  /**
   * One fetch at a time, and never a queue of them.
   *
   * Every trigger — the poll, the tab coming back, a mutation — comes through
   * here. A cashier adding six items sends six signals, and without this each
   * would start its own request: six answers racing, the list rendering
   * whichever returned last. Instead the first runs and the rest collapse into
   * exactly one follow-up, which is guaranteed to see all of them.
   *
   * Leading-edge on purpose. A debounce would make every action wait out a
   * delay to spare a burst that mostly never happens; this is instant for the
   * single action and bounded for the burst.
   */
  let fetching = false;
  let again = false;

  async function refreshNow(): Promise<void> {
    if (fetching) {
      again = true;
      return;
    }

    fetching = true;
    try {
      await refresh();
    } finally {
      fetching = false;
      if (again) {
        again = false;
        void refreshNow();
      }
    }
  }

  /**
   * The cashier's own work, the moment it settles (`D-180`, `D-181`).
   *
   * Not an optimistic removal of the row: the server's answer is a round trip
   * away, and a screen that deletes a line before the server has agreed is a
   * screen that has to put it back when the server refuses (`CLAUDE.md` §5.1
   * is the same rule about money). This asks again and draws what comes back.
   *
   * **Refusals included.** "That order is already cancelled" is another
   * terminal's work arriving as an error message, and the row it refers to is
   * still on this screen — so the refusal is the best reason there is to ask
   * again, not a reason to sit still.
   *
   * **Except with the line down.** Offline the answer is already coming from
   * the device's own copy, and a request to a server that is not there costs a
   * timeout to learn nothing. The poll keeps its own offline behaviour — it
   * refreshes the queued rows, which live here — so this guard is on the
   * settle path alone.
   */
  watch(
    () => useOrderStore().settledAt,
    () => {
      if (connection.isOnline) void refreshNow();
    },
  );

  function onVisibilityChange(): void {
    if (document.visibilityState === "visible") void refreshNow();
  }

  // Changing the tab is a different question for the server, not a filter over
  // what is already here: today's closed orders were never fetched.
  watch(view, () => void refreshNow());

  // The same question asked of the server, not a filter over rows already here:
  // the carried ones were never fetched.
  watch(includeCarried, () => void refreshNow());

  // D-081 — the line came back. Take a fresh copy of every tab now, while it is
  // there to take, rather than waiting for the next outage to discover that the
  // one on the device is a day old.
  watch(
    () => connection.isOnline,
    (online) => {
      if (online) void refreshNow().then(warmMirror);
    },
  );

  /**
   * Fill every tab's offline copy, once (D-081).
   *
   * After the visible one, so the screen the cashier is looking at is never
   * waiting behind four requests for tabs they have not opened.
   */
  async function warmMirror(): Promise<void> {
    const profile = session.profile?.name;
    if (!profile) return;

    await warm(
      profile,
      (["open", "closed", "returned", "all"] as OrderView[]).filter(
        (candidate) => candidate !== view.value,
      ),
    );
  }

  onMounted(() => {
    void refreshNow().then(warmMirror);
    timer = window.setInterval(refreshNow, REFRESH_MS);
    document.addEventListener("visibilitychange", onVisibilityChange);
  });

  onUnmounted(() => {
    window.clearInterval(timer);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  });

  return {
    error,
    loading,
    maySeeEveryone,
    older,
    searchOlder,
    searchingOlder,
    refresh: refreshNow,
    scope,
    search,
    searching: computed(() => Boolean(search.value.trim())),
    sort,
    staleAt,
    view,
    includeCarried,
    carriedCount,
    visible,
  };
}
