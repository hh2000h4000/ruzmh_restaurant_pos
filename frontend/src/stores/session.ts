import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { query } from "@/api/client";
import type { CatalogItem, OrderType, PosSession } from "@/types/session";

import { useThemeStore } from "./theme";

/**
 * The terminal's configuration for the whole shift.
 *
 * Loaded once at login (07 §2) and treated as read-only afterwards. Screens
 * read from here instead of re-fetching, which is what lets the app keep
 * working when the connection drops (09 §3).
 */
export const useSessionStore = defineStore("session", () => {
  const data = ref<PosSession | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isLoaded = computed(() => data.value !== null);
  const profile = computed(() => data.value?.pos_profile ?? null);
  const branch = computed(() => data.value?.pos_profile.branch ?? null);
  const shift = computed(() => data.value?.active_shift ?? null);

  /** BR-044 — no sales without an open shift, so the UI gates on this. */
  const hasOpenShift = computed(() => shift.value?.status === "open");

  const orderTypes = computed<OrderType[]>(() => data.value?.order_types ?? []);
  const items = computed<CatalogItem[]>(() => data.value?.items ?? []);

  /** Item lookup by code — built once instead of scanning the menu per tap. */
  const itemsByCode = computed(() => {
    const index = new Map<string, CatalogItem>();
    for (const item of items.value) index.set(item.item_code, item);
    return index;
  });

  /**
   * Permission check for hiding buttons.
   *
   * UX only. The backend re-validates every action (FR-12.3), so a wrong
   * answer here is a cosmetic bug, never a security hole.
   */
  function can(action: string): boolean {
    return Boolean(data.value?.permissions?.[action]);
  }

  function maxDiscount(scope: "item" | "order"): number {
    const key = scope === "item" ? "max_item_discount_pct" : "max_order_discount_pct";
    return Number(data.value?.permissions?.[key] ?? 0);
  }

  /** Items a given order type hides (FR-1.1). */
  function visibleItems(orderType: OrderType | null): CatalogItem[] {
    if (!orderType?.hidden_item_groups.length) return items.value;

    const hidden = new Set(orderType.hidden_item_groups);
    return items.value.filter((item) => !hidden.has(item.item_group));
  }

  async function load(posProfile: string): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      const payload = await query<PosSession>("session.load_pos_session", {
        pos_profile: posProfile,
      });

      data.value = payload;
      // Brand the app before the first screen paints.
      useThemeStore().apply(payload.theme);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      throw cause;
    } finally {
      loading.value = false;
    }
  }

  function clear(): void {
    data.value = null;
    error.value = null;
    useThemeStore().reset();
  }

  return {
    data,
    loading,
    error,
    isLoaded,
    profile,
    branch,
    shift,
    hasOpenShift,
    orderTypes,
    items,
    itemsByCode,
    can,
    maxDiscount,
    visibleItems,
    load,
    clear,
  };
});
