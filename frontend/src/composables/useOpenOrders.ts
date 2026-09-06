import { computed, onMounted, onUnmounted, ref, watch } from "vue";

import { listOrders, type OpenOrder, type OrderView } from "@/api/order";
import { t } from "@/i18n";
import { recall, remember, warm } from "@/offline/orderMirror";
import { queuedSales } from "@/offline/queue";
import { useConnectionStore } from "@/stores/connection";
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
export function useOpenOrders() {
  const session = useSessionStore();
  const connection = useConnectionStore();

  const rows = ref<OpenOrder[]>([]);
  const error = ref<string | null>(null);
  const loading = ref(false);
  /** When these rows came from the server, if they are not fresh (D-080). */
  const staleAt = ref<string | null>(null);

  const search = ref("");
  const sort = ref<OrderSort>("oldest");

  /** Which orders to ask for: open, drafts, today's history, or everything. */
  const view = ref<OrderView>("open");

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
      } satisfies OpenOrder;
    });
  }

  const visible = computed(() => {
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
      list = list.filter((order) =>
        [order.name, order.table_number, order.cashier_name, order.order_type_title_ar]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(needle)),
      );
    }

    // A copy: sorting in place would mutate what the fetch returned and make the
    // next comparison depend on the last render.
    return [...list].sort((a, b) => {
      if (sort.value === "amount") return b.total_amount - a.total_amount;
      const direction = sort.value === "newest" ? -1 : 1;
      return direction * a.opened_at.localeCompare(b.opened_at);
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
      rows.value = await listOrders(profile, view.value);
      error.value = null;
      staleAt.value = null;
      // D-080 — so the next outage still has a day's history to show.
      await remember(view.value, rows.value);
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

  /** Cheap enough to poll, and a stale row sends a cashier to the wrong table. */
  const REFRESH_MS = 15_000;
  let timer: number | undefined;

  function onVisibilityChange(): void {
    if (document.visibilityState === "visible") void refresh();
  }

  // Changing the tab is a different question for the server, not a filter over
  // what is already here: today's closed orders were never fetched.
  watch(view, () => void refresh());

  // D-081 — the line came back. Take a fresh copy of every tab now, while it is
  // there to take, rather than waiting for the next outage to discover that the
  // one on the device is a day old.
  watch(
    () => connection.isOnline,
    (online) => {
      if (online) void refresh().then(warmMirror);
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
    void refresh().then(warmMirror);
    timer = window.setInterval(refresh, REFRESH_MS);
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
    refresh,
    scope,
    search,
    searching: computed(() => Boolean(search.value.trim())),
    sort,
    staleAt,
    view,
    visible,
  };
}
