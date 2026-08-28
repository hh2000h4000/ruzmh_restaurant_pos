import { computed, onMounted, onUnmounted, ref } from "vue";

import { getOpenOrders, type OpenOrder } from "@/api/order";
import { t } from "@/i18n";
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

  const rows = ref<OpenOrder[]>([]);
  const error = ref<string | null>(null);
  const loading = ref(false);

  const search = ref("");
  const sort = ref<OrderSort>("oldest");

  /** "Mine" is the default even for a supervisor: the smaller list is the calmer one. */
  const scope = ref<OrderScope>("mine");

  /**
   * `null` hides the switch entirely. The backend enforces the same rule — without
   * the right it does not return other people's orders — so this only decides
   * whether an empty tab is worth offering.
   */
  const maySeeEveryone = computed(() => session.can("can_view_all_orders"));

  const visible = computed(() => {
    let list = rows.value;

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

    loading.value = true;
    try {
      rows.value = await getOpenOrders(profile);
      error.value = null;
    } catch (cause) {
      // The list is a convenience; a failure here must not blank the screen or
      // stop a cashier opening a new order.
      error.value = cause instanceof Error ? cause.message : t("home.openOrdersFailed");
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

  onMounted(() => {
    void refresh();
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
    visible,
  };
}
