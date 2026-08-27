<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { getOpenOrders, type OpenOrder } from "@/api/order";
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import LocaleToggle from "@/components/LocaleToggle.vue";
import { clockTime, dateOnly, formatNumber, pick, t, timeOnly, tn } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

const session = useSessionStore();
const connection = useConnectionStore();
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

/** Highlighted in the column, the way a chosen tab stays chosen. */
const lastUsedType = ref<string | null>(null);

function open(orderType: OrderType): void {
  lastUsedType.value = orderType.name;
  // FR-2.1 step 3 — a table-service order picks its table before it exists,
  // so the order is never created and then refused.
  const target = orderType.requires_table ? "tables" : "new-order";
  void router.push({ name: target, params: { orderType: orderType.name } });
}

/** The second line under an order type: what it is, in a few words. */
function typeSubtitle(orderType: OrderType): string {
  if (orderType.requires_table) return t("type.hintTable");
  if (orderType.customer_mode === "required") return t("type.hintCustomer");
  return t("type.hintQuick");
}

// --------------------------------------------------------------------------
// The floor
// --------------------------------------------------------------------------

const openOrders = ref<OpenOrder[]>([]);
const ordersError = ref<string | null>(null);
const loadingOrders = ref(false);
const search = ref("");

type SortKey = "oldest" | "newest" | "amount";
const sort = ref<SortKey>("oldest");
const sortOpen = ref(false);
const view = ref<"list" | "grid">("list");

/** "Mine" is the default even for a supervisor: it is the smaller, calmer list. */
const scope = ref<"mine" | "all">("mine");

/**
 * Whether the "all" tab exists at all. The backend enforces the same rule —
 * without the right it simply does not return other people's orders — so this
 * only decides whether an empty tab is worth showing.
 */
const maySeeEveryone = computed(() => session.can("can_view_all_orders"));

const visibleOrders = computed(() => {
  let rows = openOrders.value;

  if (maySeeEveryone.value && scope.value === "mine") {
    rows = rows.filter((order) => order.cashier === session.data?.user);
  }

  const needle = search.value.trim().toLowerCase();
  if (needle) {
    rows = rows.filter((order) =>
      [order.name, order.table_number, order.cashier_name, order.order_type_title_ar]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle)),
    );
  }

  // A copy: `sort` in place would mutate what the fetch returned and make the
  // next comparison depend on the last render.
  return [...rows].sort((a, b) => {
    if (sort.value === "amount") return b.total_amount - a.total_amount;
    const direction = sort.value === "newest" ? -1 : 1;
    return direction * a.opened_at.localeCompare(b.opened_at);
  });
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
 * Colour follows the order lifecycle and is never the only signal: every row
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

// --------------------------------------------------------------------------
// Who is on the till
// --------------------------------------------------------------------------

const cashierName = computed(() => session.data?.user_name || session.data?.user || "");

/** The POS role, which is what the badge under the name means to staff. */
const cashierRole = computed(() => {
  const roles = session.data?.permissions?.roles;
  return Array.isArray(roles) ? (roles[0] ?? "") : "";
});

const cashierInitial = computed(() => cashierName.value.trim().charAt(0) || "?");

const signingOut = ref(false);

function signOut(): void {
  // Frappe owns the session (04 §7); this app only sends the cashier to its
  // logout and lets the redirect land wherever the site says.
  window.location.href = "/api/method/logout";
}

// --------------------------------------------------------------------------
// The bottom bar — navigation only (D-033)
// --------------------------------------------------------------------------

function goToFloorPlan(): void {
  void router.push({ name: "tables", params: { orderType: orderTypes.value[0]?.name ?? "" } });
}

/** Only offered when a table-service type exists to open an order from. */
const canShowFloorPlan = computed(() =>
  orderTypes.value.some((orderType) => orderType.requires_table),
);

const pendingScreens: { key: "home.closedInvoices" | "home.reservations" | "home.shiftReport"; icon: IconName; tone: string }[] = [
  { key: "home.closedInvoices", icon: "receipt", tone: "text-accent-green" },
  { key: "home.reservations", icon: "calendar", tone: "text-accent-violet" },
  { key: "home.shiftReport", icon: "chart", tone: "text-accent-amber" },
];

const SORT_OPTIONS: { key: SortKey; label: "home.sortOldest" | "home.sortNewest" | "home.sortAmount" }[] = [
  { key: "oldest", label: "home.sortOldest" },
  { key: "newest", label: "home.sortNewest" },
  { key: "amount", label: "home.sortAmount" },
];
</script>

<template>
  <div class="flex h-screen flex-col bg-background">
    <!-- ── Top bar ──────────────────────────────────────────────────────── -->
    <header
      class="flex flex-wrap items-center gap-4 border-b border-line bg-surface px-6 py-3.5"
    >
      <div class="flex items-center gap-3">
        <span
          class="grid h-11 w-11 shrink-0 place-items-center rounded-rpos bg-primary text-primary-contrast"
          aria-hidden="true"
        >
          <AppIcon
            name="receipt"
            :size="22"
          />
        </span>
        <div class="min-w-0">
          <p class="truncate font-semibold leading-tight">
            {{ t("home.appName") }}
          </p>
          <p class="truncate text-xs text-muted">
            {{ sectionTitle }}
          </p>
        </div>
      </div>

      <!-- Search sits in the middle because it is the fastest way to find one
           order among fifty at a lunch rush. -->
      <div class="relative min-w-0 flex-1 sm:max-w-md">
        <span class="pointer-events-none absolute inset-y-0 start-4 grid place-items-center text-muted">
          <AppIcon name="search" />
        </span>
        <input
          v-model="search"
          type="search"
          :placeholder="t('home.search')"
          :aria-label="t('home.search')"
          class="min-h-tap w-full rounded-full border border-line bg-background ps-12 pe-4 text-base outline-none transition duration-200 ease-rpos focus:border-primary focus:bg-surface"
        >
      </div>

      <div class="flex items-center gap-2 sm:gap-3">
        <span
          class="rpos-numeric hidden items-center gap-1.5 text-sm font-medium text-muted lg:flex"
        >
          <AppIcon
            name="clock"
            :size="18"
          />
          {{ now }}
        </span>

        <!-- Not a notification bell: the only thing a till genuinely has to
             raise is work still waiting to reach the server. -->
        <div
          v-if="connection.hasBacklog"
          class="relative grid h-11 w-11 place-items-center rounded-full bg-accent-amber/10 text-accent-amber"
          :title="t('conn.syncing')"
        >
          <AppIcon name="bell" />
          <span
            class="rpos-numeric absolute -top-1 end-0 grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-accent-amber px-1 text-xs font-semibold text-white"
          >{{ connection.pending + connection.failed }}</span>
        </div>

        <span
          class="hidden rounded-full px-3 py-1.5 text-sm font-medium sm:block"
          :class="
            session.hasOpenShift
              ? 'bg-status-available/10 text-status-available'
              : 'bg-status-reserved/10 text-status-reserved'
          "
        >
          {{ session.hasOpenShift ? t("home.shiftOpen") : t("home.shiftClosed") }}
        </span>

        <LocaleToggle />

        <div class="flex items-center gap-2.5">
          <div class="hidden text-end md:block">
            <p class="text-sm font-semibold leading-tight">
              {{ cashierName }}
            </p>
            <p class="text-xs text-muted">
              {{ cashierRole }}
            </p>
          </div>
          <span
            class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary/10 text-base font-semibold uppercase text-primary"
            aria-hidden="true"
          >{{ cashierInitial }}</span>
        </div>
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
      class="flex min-h-0 flex-1 gap-5 p-5"
    >
      <!-- ── Order types ───────────────────────────────────────────────── -->
      <aside class="w-64 shrink-0 overflow-y-auto">
        <h2 class="mb-3 text-center text-sm font-medium text-muted">
          {{ t("home.newOrder") }}
        </h2>

        <div class="flex flex-col gap-2.5">
          <button
            v-for="orderType in orderTypes"
            :key="orderType.name"
            type="button"
            class="flex min-h-tap items-center gap-3 rounded-rpos-lg border p-3 text-start transition duration-200 ease-rpos"
            :class="
              lastUsedType === orderType.name
                ? 'border-transparent bg-primary text-primary-contrast shadow-lift'
                : 'border-line bg-surface hover:-translate-y-px hover:shadow-card'
            "
            @click="open(orderType)"
          >
            <!-- The type's own colour lives in the tile, tinted, so it marks
                 the row without fighting the label for contrast. -->
            <span class="relative grid h-12 w-12 shrink-0 place-items-center overflow-hidden rounded-rpos">
              <span
                class="absolute inset-0"
                :class="lastUsedType === orderType.name ? 'bg-white/20' : 'opacity-10'"
                :style="
                  lastUsedType === orderType.name ? undefined : { backgroundColor: orderType.color ?? undefined }
                "
                aria-hidden="true"
              />
              <span
                v-if="orderType.icon"
                class="relative text-xl leading-none"
                aria-hidden="true"
              >{{ orderType.icon }}</span>
              <AppIcon
                v-else
                class="relative"
                name="document"
                :size="22"
              />
            </span>

            <span class="min-w-0">
              <span class="block truncate font-semibold">
                {{ pick(orderType.title_ar, orderType.title) }}
              </span>
              <span
                class="block truncate text-xs"
                :class="lastUsedType === orderType.name ? 'opacity-80' : 'text-muted'"
              >{{ typeSubtitle(orderType) }}</span>
            </span>
          </button>
        </div>

        <p
          v-if="!orderTypes.length"
          class="text-sm text-muted"
        >
          {{ t("home.noOrderTypes") }}
        </p>
      </aside>

      <!-- ── The floor ─────────────────────────────────────────────────── -->
      <main class="flex min-w-0 flex-1 flex-col rounded-rpos-lg bg-surface p-5 shadow-card">
        <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 class="flex items-center gap-2 text-lg font-semibold">
              <AppIcon
                name="document"
                :size="22"
              />
              {{ t("home.openOrders") }}
            </h2>
            <p class="mt-0.5 text-sm text-muted">
              <span class="rpos-numeric font-semibold text-primary">
                {{ formatNumber(visibleOrders.length) }}
              </span>
              {{ t("home.openOrdersUnit") }}
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <!-- Shown only to someone who may see the whole floor; the backend
                 enforces the same rule regardless (FR-12.3). -->
            <div
              v-if="maySeeEveryone"
              class="flex rounded-full bg-background p-1"
              role="group"
            >
              <button
                v-for="option in (['mine', 'all'] as const)"
                :key="option"
                type="button"
                class="min-h-tap rounded-full px-5 text-sm font-medium transition duration-200 ease-rpos"
                :class="scope === option ? 'bg-primary text-primary-contrast' : 'text-muted'"
                :aria-pressed="scope === option"
                @click="scope = option"
              >
                {{ option === "mine" ? t("home.scopeMine") : t("home.scopeAll") }}
              </button>
            </div>

            <div class="flex rounded-rpos bg-background p-1">
              <button
                v-for="option in (['grid', 'list'] as const)"
                :key="option"
                type="button"
                class="grid h-11 w-11 place-items-center rounded-rpos transition duration-200 ease-rpos"
                :class="view === option ? 'bg-primary text-primary-contrast' : 'text-muted'"
                :aria-pressed="view === option"
                :aria-label="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
                :title="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
                @click="view = option"
              >
                <AppIcon :name="option" />
              </button>
            </div>
          </div>
        </div>

        <p
          v-if="ordersError"
          role="alert"
          class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
        >
          {{ ordersError }}
        </p>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <!-- List view: one row per order, each column a value over its label,
               which is how a cashier scans a stack of bills. -->
          <div
            v-if="visibleOrders.length && view === 'list'"
            class="flex flex-col gap-3"
          >
            <button
              v-for="order in visibleOrders"
              :key="order.name"
              type="button"
              class="flex w-full flex-wrap items-center justify-between gap-4 rounded-rpos-lg border border-line bg-surface p-4 text-start transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-card"
              @click="resume(order)"
            >
              <div class="flex min-w-0 items-center gap-3">
                <span
                  class="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-primary/10 text-primary"
                  aria-hidden="true"
                >
                  <AppIcon name="user" />
                </span>
                <div class="min-w-0">
                  <p class="truncate font-medium">
                    {{ order.cashier_name }}
                  </p>
                  <p class="truncate text-xs text-muted">
                    {{ t("card.cashier") }}
                  </p>
                </div>
              </div>

              <div class="min-w-0">
                <p class="truncate font-semibold">
                  {{ whereLabel(order) }}
                </p>
                <p class="rpos-numeric truncate text-xs text-muted">
                  {{ order.name }}
                </p>
              </div>

              <div class="hidden sm:block">
                <p class="rpos-numeric font-medium">
                  {{ dateOnly(order.opened_at) }}
                </p>
                <p class="rpos-numeric text-xs text-muted">
                  {{ timeOnly(order.opened_at) }}
                </p>
              </div>

              <div class="text-center">
                <span
                  class="rpos-numeric grid h-9 w-9 place-items-center rounded-full bg-background text-sm font-semibold"
                >{{ formatNumber(order.item_count) }}</span>
                <p class="mt-1 text-xs text-muted">
                  {{ t("card.itemCount") }}
                </p>
              </div>

              <div>
                <p class="rpos-numeric text-xl font-bold text-primary">
                  {{ formatNumber(order.total_amount, 2) }}
                </p>
                <p class="text-xs text-muted">
                  {{ t("card.amount") }}
                </p>
              </div>

              <!-- Colour plus words: never colour alone (06 §Accessibility). -->
              <span
                class="shrink-0 rounded-full px-3 py-1.5 text-xs font-medium"
                :class="STATUS_CLASS[order.status]"
              >
                {{ t(`status.${order.status}`) }}
              </span>
            </button>
          </div>

          <!-- Card view: the same orders, when the floor is read by table. -->
          <div
            v-else-if="visibleOrders.length"
            class="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-3"
          >
            <button
              v-for="order in visibleOrders"
              :key="order.name"
              type="button"
              class="flex flex-col gap-3 rounded-rpos-lg border border-line bg-surface p-4 text-start transition duration-200 ease-rpos hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-card"
              @click="resume(order)"
            >
              <div class="flex items-start justify-between gap-2">
                <span class="truncate text-base font-semibold">{{ whereLabel(order) }}</span>
                <span
                  class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium"
                  :class="STATUS_CLASS[order.status]"
                >{{ t(`status.${order.status}`) }}</span>
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
                  <p class="truncate text-xs text-muted">
                    {{ order.cashier_name }}
                  </p>
                </div>
                <span class="rpos-numeric shrink-0 text-xl font-bold text-primary">
                  {{ formatNumber(order.total_amount, 2) }}
                </span>
              </div>
            </button>
          </div>

          <div
            v-else-if="!loadingOrders"
            class="grid place-items-center px-6 py-20 text-center"
          >
            <span class="mb-3 text-muted opacity-40">
              <AppIcon
                name="receipt"
                :size="48"
              />
            </span>
            <p class="text-muted">
              {{ search.trim() ? t("home.searchEmpty") : t("home.openOrdersEmpty") }}
            </p>
          </div>
        </div>
      </main>
    </div>

    <!-- ── Bottom bar ───────────────────────────────────────────────────── -->
    <nav class="flex flex-wrap items-center gap-2.5 border-t border-line bg-surface px-5 py-3">
      <button
        v-if="canShowFloorPlan"
        type="button"
        class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-accent-blue/10 px-4 text-sm font-medium text-accent-blue transition duration-200 ease-rpos hover:bg-accent-blue/20"
        @click="goToFloorPlan"
      >
        <AppIcon name="floorPlan" />
        {{ t("home.floorPlan") }}
      </button>

      <!-- These screens do not exist yet, so their buttons are visibly
           unavailable rather than routed somewhere empty. -->
      <button
        v-for="screen in pendingScreens"
        :key="screen.key"
        type="button"
        disabled
        class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-background px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40"
        :class="screen.tone"
        :title="t('common.soon')"
      >
        <AppIcon :name="screen.icon" />
        {{ t(screen.key) }}
      </button>

      <div class="relative flex-1">
        <button
          type="button"
          class="flex min-h-tap w-full items-center justify-center gap-2 rounded-rpos bg-accent-slate/10 px-4 text-sm font-medium text-accent-slate transition duration-200 ease-rpos hover:bg-accent-slate/20"
          :aria-expanded="sortOpen"
          @click="sortOpen = !sortOpen"
        >
          <AppIcon name="sort" />
          {{ t("home.sort") }}
        </button>

        <div
          v-if="sortOpen"
          class="absolute bottom-full mb-2 w-full overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
        >
          <button
            v-for="option in SORT_OPTIONS"
            :key="option.key"
            type="button"
            class="block w-full px-4 text-start text-sm transition duration-200 ease-rpos hover:bg-background"
            :class="sort === option.key ? 'font-semibold text-primary' : ''"
            @click="((sort = option.key), (sortOpen = false))"
          >
            {{ t(option.label) }}
          </button>
        </div>
      </div>

      <button
        type="button"
        class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-accent-teal/10 px-4 text-sm font-medium text-accent-teal transition duration-200 ease-rpos hover:bg-accent-teal/20 disabled:opacity-50"
        :disabled="loadingOrders"
        @click="refresh"
      >
        <AppIcon
          name="refresh"
          :class="{ 'animate-spin': loadingOrders }"
        />
        {{ t("action.refresh") }}
      </button>

      <button
        type="button"
        class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-accent-rose/10 px-4 text-sm font-medium text-accent-rose transition duration-200 ease-rpos hover:bg-accent-rose/20"
        @click="signingOut = true"
      >
        <AppIcon name="logout" />
        {{ t("home.logout") }}
      </button>
    </nav>

    <!-- Signing out mid-shift by accident is a real annoyance at a till. -->
    <BaseDialog
      :open="signingOut"
      :title="t('home.logoutConfirm')"
      :dismissible="true"
      @close="signingOut = false"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("home.logoutBody") }}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="signingOut = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white"
          @click="signOut"
        >
          {{ t("home.logout") }}
        </button>
      </div>
    </BaseDialog>
  </div>
</template>
