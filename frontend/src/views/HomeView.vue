<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { getOpenOrders, type OpenOrder } from "@/api/order";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { money, pick, t, tn } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

const session = useSessionStore();
const router = useRouter();

const sectionTitle = computed(
  () =>
    pick(session.data?.restaurant_section?.title_ar, session.data?.restaurant_section?.title) ||
    session.branch ||
    "",
);

/**
 * FR-1.3 — the backend already filtered these by role, terminal and branch, so
 * the screen renders what it is given rather than filtering again. A second
 * filter here could disagree with the one that accepts the order.
 */
const orderTypes = computed(() => session.orderTypes);

function open(orderType: OrderType): void {
  // FR-2.1 step 3 — a table-service order picks its table before it exists,
  // so the order is never created and then refused.
  const target = orderType.requires_table ? "tables" : "new-order";
  void router.push({ name: target, params: { orderType: orderType.name } });
}

// --------------------------------------------------------------------------
// Open orders
// --------------------------------------------------------------------------

const openOrders = ref<OpenOrder[]>([]);
const ordersError = ref<string | null>(null);
const loadingOrders = ref(false);

/** Cheap enough to poll, and a stale card sends a cashier to the wrong table. */
const REFRESH_MS = 15_000;
let timer: number | undefined;

async function refresh(): Promise<void> {
  const profile = session.profile?.name;
  if (!profile) return;

  loadingOrders.value = true;
  try {
    openOrders.value = await getOpenOrders(profile);
    ordersError.value = null;
  } catch (cause) {
    // The list is a convenience; a failure here must not blank the screen or
    // block a cashier from opening a new order.
    ordersError.value = cause instanceof Error ? cause.message : t("home.openOrdersFailed");
  } finally {
    loadingOrders.value = false;
  }
}

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

function resume(order: OpenOrder): void {
  void router.push({ name: "order", params: { orderName: order.name } });
}

/**
 * Colour follows the order lifecycle and is never the only signal: every card
 * also spells its status out (06 §Accessibility).
 */
const STATUS_CLASS: Record<OpenOrder["status"], string> = {
  draft: "bg-order-draft",
  active: "bg-order-active",
  in_kitchen: "bg-order-in_kitchen",
  pending_payment: "bg-order-pending_payment",
};

function whereLabel(order: OpenOrder): string {
  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

/**
 * The bottom bar is navigation, never an action on a selected card.
 *
 * A button that acts on "the highlighted order" needs a selection mode, and at
 * a busy till that is how a refund lands on the wrong bill. Order actions live
 * on the order screen, where the order is unambiguous and every one of them is
 * permission-checked.
 *
 * These three screens are not built yet, so they are disabled rather than
 * routed somewhere empty — a dead button hides what is missing.
 */
const bottomActions = [
  { key: "home.closedInvoices", icon: "📋" },
  { key: "home.reservations", icon: "📅" },
  { key: "home.shiftReport", icon: "📊" },
] as const;
</script>

<template>
  <div class="flex h-screen flex-col">
    <header class="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
      <div>
        <h1 class="text-xl font-semibold">
          {{ sectionTitle }}
        </h1>
        <p class="text-sm text-muted">
          {{ session.data?.pos_profile.name }}
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div
          v-if="session.hasOpenShift"
          class="rounded-rpos bg-status-available/10 px-3 py-1.5 text-sm text-status-available"
        >
          {{ t("home.shiftOpen") }}
        </div>
        <div
          v-else
          class="rounded-rpos bg-status-reserved/10 px-3 py-1.5 text-sm text-status-reserved"
        >
          {{ t("home.shiftClosed") }}
        </div>

        <LocaleToggle />
      </div>
    </header>

    <!-- BR-044: no order can be created without an open shift, so say so
         instead of showing buttons that will be refused. -->
    <section
      v-if="!session.hasOpenShift"
      class="m-4 rounded-rpos bg-surface p-6 text-center"
    >
      <p class="mb-2">
        {{ t("home.shiftRequired") }}
      </p>
      <p class="text-sm text-muted">
        {{ t("home.shiftFromDesk") }}
      </p>
    </section>

    <div
      v-else
      class="flex min-h-0 flex-1"
    >
      <!-- Order types. The column sits at the inline start, so it follows the
           document direction: right in Arabic, left in English, with no
           direction-specific CSS. -->
      <aside class="w-40 shrink-0 overflow-y-auto border-e border-line bg-surface p-3 sm:w-48">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("home.newOrder") }}
        </h2>

        <div class="flex flex-col gap-2">
          <button
            v-for="orderType in orderTypes"
            :key="orderType.name"
            type="button"
            class="flex min-h-tap items-center gap-2 rounded-rpos bg-background p-3 text-start shadow-sm transition hover:shadow focus:outline-none focus:ring-2 focus:ring-primary"
            :style="orderType.color ? { borderInlineStartWidth: '4px', borderInlineStartColor: orderType.color } : undefined"
            @click="open(orderType)"
          >
            <span
              v-if="orderType.icon"
              class="text-2xl"
              aria-hidden="true"
            >{{ orderType.icon }}</span>
            <span class="text-sm font-medium">{{ pick(orderType.title_ar, orderType.title) }}</span>
          </button>
        </div>

        <p
          v-if="!orderTypes.length"
          class="text-sm text-muted"
        >
          {{ t("home.noOrderTypes") }}
        </p>
      </aside>

      <!-- Open orders -->
      <main class="min-w-0 flex-1 overflow-y-auto p-4">
        <div class="mb-3 flex items-center justify-between gap-3">
          <h2 class="text-sm font-medium text-muted">
            {{ t("home.openOrders") }} — {{ tn("count.openOrders", openOrders.length) }}
          </h2>
          <button
            type="button"
            class="rounded-rpos px-2 py-1 text-sm text-muted underline disabled:opacity-50"
            :disabled="loadingOrders"
            @click="refresh"
          >
            {{ loadingOrders ? t("common.loading") : t("action.refresh") }}
          </button>
        </div>

        <p
          v-if="ordersError"
          role="alert"
          class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
        >
          {{ ordersError }}
        </p>

        <div
          v-if="openOrders.length"
          class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        >
          <button
            v-for="order in openOrders"
            :key="order.name"
            type="button"
            class="rounded-rpos bg-surface p-3 text-start shadow-sm transition hover:shadow focus:outline-none focus:ring-2 focus:ring-primary"
            @click="resume(order)"
          >
            <div class="mb-2 flex items-center justify-between gap-2">
              <span class="truncate font-medium">
                <span
                  v-if="order.icon"
                  aria-hidden="true"
                >{{ order.icon }} </span>
                {{ whereLabel(order) }}
              </span>
              <span class="shrink-0 text-xs text-muted">{{ order.name }}</span>
            </div>

            <div class="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
              <span>{{ tn("count.minutes", order.order_minutes) }}</span>
              <span>{{ tn("count.items", order.item_count) }}</span>
              <span v-if="order.cover_count">{{ tn("count.covers", order.cover_count) }}</span>
            </div>

            <div class="flex items-center justify-between gap-2">
              <!-- Colour plus words: never colour alone (06 §Accessibility). -->
              <span class="flex items-center gap-1.5 text-sm">
                <span
                  class="inline-block h-2.5 w-2.5 rounded-full"
                  :class="STATUS_CLASS[order.status]"
                  aria-hidden="true"
                />
                {{ t(`status.${order.status}`) }}
              </span>
              <span class="font-medium">{{ money(order.total_amount, session.profile?.currency) }}</span>
            </div>
          </button>
        </div>

        <p
          v-else-if="!loadingOrders"
          class="rounded-rpos bg-surface p-6 text-center text-muted"
        >
          {{ t("home.openOrdersEmpty") }}
        </p>
      </main>
    </div>

    <nav class="flex flex-wrap gap-2 border-t border-line px-4 py-2">
      <button
        v-for="action in bottomActions"
        :key="action.key"
        type="button"
        disabled
        class="flex min-h-tap items-center gap-2 rounded-rpos px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
        :title="t('common.soon')"
      >
        <span aria-hidden="true">{{ action.icon }}</span>
        <span>{{ t(action.key) }}</span>
      </button>
    </nav>
  </div>
</template>
