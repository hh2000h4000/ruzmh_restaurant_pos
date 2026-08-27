<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { getOpenOrders, type OpenOrder } from "@/api/order";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { clockTime, money, pick, t, tn } from "@/i18n";
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
// The floor
// --------------------------------------------------------------------------

const openOrders = ref<OpenOrder[]>([]);
const ordersError = ref<string | null>(null);
const loadingOrders = ref(false);

/** "Mine" is the default even for a supervisor: it is the smaller, calmer list. */
const scope = ref<"mine" | "all">("mine");

/**
 * Whether the "all" tab exists at all. The backend enforces the same rule —
 * without the right it simply does not return other people's orders — so this
 * only decides whether an empty tab is worth showing.
 */
const maySeeEveryone = computed(() => session.can("can_view_all_orders"));

const visibleOrders = computed(() => {
  if (!maySeeEveryone.value || scope.value === "all") return openOrders.value;
  return openOrders.value.filter((order) => order.cashier === session.data?.user);
});

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

// The clock is part of the furniture on a till: staff read it off this screen
// all shift. Minutes, not seconds — a second hand is motion nobody asked for.
const now = ref(clockTime());
let clock: number | undefined;

onMounted(() => {
  void refresh();
  timer = window.setInterval(refresh, REFRESH_MS);
  clock = window.setInterval(() => (now.value = clockTime()), 15_000);
  document.addEventListener("visibilitychange", onVisibilityChange);
});

onUnmounted(() => {
  window.clearInterval(timer);
  window.clearInterval(clock);
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
  draft: "bg-order-draft/10 text-order-draft",
  active: "bg-order-active/10 text-order-active",
  in_kitchen: "bg-order-in_kitchen/10 text-order-in_kitchen",
  pending_payment: "bg-order-pending_payment/10 text-order-pending_payment",
};

function whereLabel(order: OpenOrder): string {
  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

const cashierName = computed(() => session.data?.user_name || session.data?.user || "");

/** First letter of the name on duty, for the header badge. */
const cashierInitial = computed(() => cashierName.value.trim().charAt(0) || "?");

function goToFloorPlan(): void {
  void router.push({ name: "tables", params: { orderType: orderTypes.value[0]?.name ?? "" } });
}

/**
 * The bottom bar is navigation, never an action on a selected card.
 *
 * A button that acts on "the highlighted order" needs a selection mode, and at
 * a busy till that is how a refund lands on the wrong bill. Order actions live
 * on the order screen, where the order is unambiguous and every one of them is
 * permission-checked.
 */
const pendingScreens = [
  { key: "home.closedInvoices", icon: "🧾" },
  { key: "home.reservations", icon: "📅" },
  { key: "home.shiftReport", icon: "📊" },
] as const;

/** Only offered when a table-service type exists to open an order from. */
const canShowFloorPlan = computed(() =>
  orderTypes.value.some((orderType) => orderType.requires_table),
);
</script>

<template>
  <div class="flex h-screen flex-col bg-background">
    <header
      class="flex flex-wrap items-center justify-between gap-4 border-b border-line bg-surface px-5 py-3 shadow-bar"
    >
      <div class="min-w-0">
        <h1 class="truncate text-xl font-semibold tracking-tight">
          {{ sectionTitle }}
        </h1>
        <p class="truncate text-sm text-muted">
          {{ session.data?.pos_profile.name }}
        </p>
      </div>

      <div class="flex items-center gap-3">
        <span
          class="rpos-numeric hidden text-2xl font-semibold tabular-nums sm:block"
          aria-hidden="true"
        >{{ now }}</span>

        <span
          class="rounded-full px-3 py-1.5 text-sm font-medium"
          :class="
            session.hasOpenShift
              ? 'bg-status-available/10 text-status-available'
              : 'bg-status-reserved/10 text-status-reserved'
          "
        >
          {{ session.hasOpenShift ? t("home.shiftOpen") : t("home.shiftClosed") }}
        </span>

        <div class="flex items-center gap-2">
          <span
            class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold uppercase text-primary"
            aria-hidden="true"
          >{{ cashierInitial }}</span>
          <span class="hidden text-sm font-medium md:block">{{ cashierName }}</span>
        </div>

        <LocaleToggle />
      </div>
    </header>

    <!-- BR-044: no order can be created without an open shift, so say so
         instead of showing buttons that will be refused. -->
    <section
      v-if="!session.hasOpenShift"
      class="m-auto max-w-md rounded-rpos-lg bg-surface p-10 text-center shadow-card"
    >
      <p class="mb-2 text-lg font-medium">
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
      <aside class="w-44 shrink-0 overflow-y-auto border-e border-line bg-surface p-3 lg:w-56">
        <h2 class="mb-3 px-1 text-xs font-semibold uppercase tracking-wider text-muted">
          {{ t("home.newOrder") }}
        </h2>

        <div class="flex flex-col gap-2">
          <button
            v-for="orderType in orderTypes"
            :key="orderType.name"
            type="button"
            class="group relative flex min-h-tap items-center gap-3 overflow-hidden rounded-rpos bg-background px-3 py-3 text-start transition duration-200 ease-rpos hover:-translate-y-px hover:shadow-card focus:outline-none focus:ring-2 focus:ring-primary"
            @click="open(orderType)"
          >
            <!-- The type's own colour, as a spine rather than a fill: it marks
                 the row without fighting the text for contrast. -->
            <span
              class="absolute inset-y-0 start-0 w-1"
              :style="{ backgroundColor: orderType.color ?? 'transparent' }"
              aria-hidden="true"
            />
            <span
              v-if="orderType.icon"
              class="text-2xl leading-none"
              aria-hidden="true"
            >{{ orderType.icon }}</span>
            <span class="truncate text-sm font-medium">
              {{ pick(orderType.title_ar, orderType.title) }}
            </span>
          </button>
        </div>

        <p
          v-if="!orderTypes.length"
          class="px-1 text-sm text-muted"
        >
          {{ t("home.noOrderTypes") }}
        </p>
      </aside>

      <!-- The floor -->
      <main class="flex min-w-0 flex-1 flex-col">
        <div class="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <h2 class="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted">
            {{ t("home.openOrders") }}
            <span class="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary">
              {{ visibleOrders.length }}
            </span>
          </h2>

          <div class="flex items-center gap-2">
            <!-- Shown only to someone who may see the whole floor; the backend
                 enforces the same rule regardless (FR-12.3). -->
            <div
              v-if="maySeeEveryone"
              class="flex rounded-full bg-surface p-1 shadow-card"
              role="group"
            >
              <button
                v-for="option in (['mine', 'all'] as const)"
                :key="option"
                type="button"
                class="min-h-tap rounded-full px-5 text-sm font-medium transition duration-200 ease-rpos"
                :class="
                  scope === option ? 'bg-primary text-primary-contrast shadow-card' : 'text-muted'
                "
                :aria-pressed="scope === option"
                @click="scope = option"
              >
                {{ option === "mine" ? t("home.scopeMine") : t("home.scopeAll") }}
              </button>
            </div>

            <button
              type="button"
              class="grid h-12 w-12 place-items-center rounded-full bg-surface text-muted shadow-card transition duration-200 ease-rpos hover:text-content disabled:opacity-50"
              :disabled="loadingOrders"
              :aria-label="t('action.refresh')"
              :title="t('action.refresh')"
              @click="refresh"
            >
              <span
                class="text-lg"
                :class="{ 'animate-spin': loadingOrders }"
                aria-hidden="true"
              >⟳</span>
            </button>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto px-5 pb-5">
          <p
            v-if="ordersError"
            role="alert"
            class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
          >
            {{ ordersError }}
          </p>

          <div
            v-if="visibleOrders.length"
            class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
          >
            <button
              v-for="order in visibleOrders"
              :key="order.name"
              type="button"
              class="group relative flex flex-col gap-3 overflow-hidden rounded-rpos-lg bg-surface p-4 text-start shadow-card transition duration-200 ease-rpos hover:-translate-y-0.5 hover:shadow-lift focus:outline-none focus:ring-2 focus:ring-primary"
              @click="resume(order)"
            >
              <span
                class="absolute inset-y-0 start-0 w-1"
                :style="{ backgroundColor: order.color ?? 'transparent' }"
                aria-hidden="true"
              />

              <div class="flex items-start justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2">
                  <span
                    v-if="order.icon"
                    class="text-xl leading-none"
                    aria-hidden="true"
                  >{{ order.icon }}</span>
                  <span class="truncate text-base font-semibold">{{ whereLabel(order) }}</span>
                </div>

                <!-- Colour plus words: never colour alone (06 §Accessibility). -->
                <span
                  class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium"
                  :class="STATUS_CLASS[order.status]"
                >
                  {{ t(`status.${order.status}`) }}
                </span>
              </div>

              <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <span>{{ tn("count.minutes", order.order_minutes) }}</span>
                <span aria-hidden="true">·</span>
                <span>{{ tn("count.items", order.item_count) }}</span>
                <template v-if="order.cover_count">
                  <span aria-hidden="true">·</span>
                  <span>{{ tn("count.covers", order.cover_count) }}</span>
                </template>
              </div>

              <div class="flex items-end justify-between gap-2 border-t border-line pt-3">
                <div class="min-w-0">
                  <p class="rpos-numeric truncate text-xs text-muted">
                    {{ order.name }}
                  </p>
                  <p
                    v-if="order.cashier_name"
                    class="truncate text-xs text-muted"
                  >
                    {{ order.cashier_name }}
                  </p>
                </div>
                <span class="rpos-numeric shrink-0 text-lg font-semibold">
                  {{ money(order.total_amount, session.profile?.currency) }}
                </span>
              </div>
            </button>
          </div>

          <div
            v-else-if="!loadingOrders"
            class="grid place-items-center rounded-rpos-lg bg-surface/60 px-6 py-16 text-center"
          >
            <span
              class="mb-3 text-4xl opacity-40"
              aria-hidden="true"
            >🍽️</span>
            <p class="text-muted">
              {{ t("home.openOrdersEmpty") }}
            </p>
          </div>
        </div>
      </main>
    </div>

    <nav class="flex flex-wrap gap-2 border-t border-line bg-surface px-5 py-2.5">
      <button
        v-if="canShowFloorPlan"
        type="button"
        class="flex min-h-tap items-center gap-2 rounded-rpos px-4 text-sm font-medium transition duration-200 ease-rpos hover:bg-background"
        @click="goToFloorPlan"
      >
        <span aria-hidden="true">🪑</span>
        <span>{{ t("home.floorPlan") }}</span>
      </button>

      <!-- These screens do not exist yet, so their buttons are visibly
           unavailable rather than routed somewhere empty. -->
      <button
        v-for="screen in pendingScreens"
        :key="screen.key"
        type="button"
        disabled
        class="flex min-h-tap items-center gap-2 rounded-rpos px-4 text-sm disabled:cursor-not-allowed disabled:opacity-40"
        :title="t('common.soon')"
      >
        <span aria-hidden="true">{{ screen.icon }}</span>
        <span>{{ t(screen.key) }}</span>
      </button>
    </nav>
  </div>
</template>
