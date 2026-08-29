import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { ApiError, query } from "@/api/client";
import { initLocale } from "@/i18n";
import { loadSession, saveSession } from "@/offline/cache";
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
  /** Set when this session came from the device cache instead of the server. */
  const cachedAt = ref<string | null>(null);

  const isLoaded = computed(() => data.value !== null);
  const profile = computed(() => data.value?.pos_profile ?? null);
  const branch = computed(() => data.value?.pos_profile.branch ?? null);
  /**
   * BR-044 — may this cashier ring a sale right now (D-054).
   *
   * The server's answer, taken whole. It used to be `active_shift.status`,
   * which is the **day** — so a cashier who closed their till kept selling,
   * because the day was still open behind them. The rule (an open day and a
   * drawer of their own) lives on the server; nothing here re-derives it.
   */
  const canSell = computed(() => data.value?.can_sell === true);

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

  /**
   * What this item costs on an order of this type (FR-1.6).
   *
   * A delivery platform takes a commission, so its menu is priced above the
   * dining room's. The server sends every list the terminal can sell from, so
   * this answers correctly during an outage too.
   *
   * `null` means no price is configured, which is not the same as free: the
   * backend refuses to sell it (D-020).
   */
  function priceOf(item: CatalogItem, orderType: OrderType | null): number | null {
    const list = orderType?.selling_price_list;
    if (list) return item.rates[list] ?? null;
    return item.rate;
  }

  /** Items a given order type hides (FR-1.1). */
  function visibleItems(orderType: OrderType | null): CatalogItem[] {
    if (!orderType?.hidden_item_groups.length) return items.value;

    const hidden = new Set(orderType.hidden_item_groups);
    return items.value.filter((item) => !hidden.has(item.item_group));
  }

  function adopt(payload: PosSession): void {
    data.value = payload;
    // Brand the app before the first screen paints.
    useThemeStore().apply(payload.theme);
    // Only used when this terminal has no stored choice of its own; a shared
    // till keeps the language it was set up in (`i18n/index.ts`).
    initLocale(payload.lang);
  }

  async function load(posProfile: string): Promise<void> {
    loading.value = true;
    error.value = null;

    try {
      const payload = await query<PosSession>("session.load_pos_session", {
        pos_profile: posProfile,
      });

      adopt(payload);
      cachedAt.value = null;
      void saveSession(payload);
    } catch (cause) {
      // A till that reboots during an outage must come back with its menu and
      // its permissions rather than a setup screen (09 §3). Only an outage
      // qualifies: a refusal from the server is a real answer, and starting
      // from cache would hide it.
      const offline = cause instanceof ApiError && cause.isOffline;
      const cached = offline ? await loadSession() : null;

      if (cached) {
        adopt(cached.session);
        cachedAt.value = cached.cached_at;
      } else {
        error.value = cause instanceof Error ? cause.message : String(cause);
        throw cause;
      }
    } finally {
      loading.value = false;
    }
  }

  function clear(): void {
    data.value = null;
    error.value = null;
    cachedAt.value = null;
    useThemeStore().reset();
  }

  return {
    data,
    loading,
    error,
    cachedAt,
    isLoaded,
    profile,
    branch,
    canSell,
    orderTypes,
    items,
    itemsByCode,
    can,
    maxDiscount,
    priceOf,
    visibleItems,
    load,
    clear,
  };
});
