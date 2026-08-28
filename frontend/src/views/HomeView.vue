<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";

import type { OpenOrder } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import OpenOrdersPanel from "@/components/pos/OpenOrdersPanel.vue";
import OrderTypeSidebar from "@/components/pos/OrderTypeSidebar.vue";
import PosBottomBar, { type BottomAction } from "@/components/pos/PosBottomBar.vue";
import PosHeader from "@/components/pos/PosHeader.vue";
import { useOpenOrders } from "@/composables/useOpenOrders";
import { pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

/**
 * Screen 1 — the screen a till sits on all day.
 *
 * This file is the layout and the state; the four components under
 * `components/pos/` draw it. Everything they render is data — order types from
 * the session, orders from the API, bottom-bar entries from an array — so
 * adding a screen later is a row in a list, not a new branch in a template.
 *
 * Refs: 06 Screen 1, D-033
 */
const session = useSessionStore();
const router = useRouter();

const sectionTitle = computed(
  () =>
    pick(session.data?.restaurant_section?.title_ar, session.data?.restaurant_section?.title) ||
    session.branch ||
    "",
);

/** FR-1.3 — already filtered by role, terminal and branch on the server. */
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

// --------------------------------------------------------------------------
// The floor
// --------------------------------------------------------------------------

const {
  error: ordersError,
  loading: loadingOrders,
  maySeeEveryone,
  refresh,
  scope,
  search,
  searching,
  sort,
  visible: visibleOrders,
} = useOpenOrders();

const layout = ref<"list" | "grid">("list");
const sortOpen = ref(false);

function resume(order: OpenOrder): void {
  void router.push({ name: "order", params: { orderName: order.name } });
}

// --------------------------------------------------------------------------
// The bottom bar
// --------------------------------------------------------------------------

/** Only offered when a table-service type exists to open an order from. */
const canShowFloorPlan = computed(() =>
  orderTypes.value.some((orderType) => orderType.requires_table),
);

const bottomActions = computed<BottomAction[]>(() => [
  {
    key: "floor",
    label: "home.floorPlan",
    icon: "floorPlan",
    tone: "bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20",
    disabled: !canShowFloorPlan.value,
  },
  {
    key: "closed",
    label: "home.closedInvoices",
    icon: "receipt",
    tone: "bg-accent-teal/10 text-accent-teal",
    disabled: true,
  },
  {
    key: "reservations",
    label: "home.reservations",
    icon: "calendar",
    tone: "bg-accent-violet/10 text-accent-violet",
    disabled: true,
  },
  {
    key: "shift",
    label: "home.shiftReport",
    icon: "chart",
    tone: "bg-accent-amber/10 text-accent-amber",
    disabled: true,
  },
  {
    key: "sort",
    label: "home.sort",
    icon: "sort",
    tone: "bg-accent-slate/10 text-accent-slate hover:bg-accent-slate/20",
  },
  {
    key: "refresh",
    label: "action.refresh",
    icon: "refresh",
    tone: "bg-accent-green/10 text-accent-green hover:bg-accent-green/20",
    disabled: loadingOrders.value,
  },
  {
    key: "logout",
    label: "home.logout",
    icon: "logout",
    tone: "bg-accent-rose/10 text-accent-rose hover:bg-accent-rose/20",
  },
]);

const signingOut = ref(false);

function showFloorPlan(): void {
  void router.push({ name: "tables", params: { orderType: orderTypes.value[0]?.name ?? "" } });
}

function onAction(action: BottomAction): void {
  if (action.key === "floor") {
    showFloorPlan();
  } else if (action.key === "refresh") {
    void refresh();
  } else if (action.key === "sort") {
    sortOpen.value = !sortOpen.value;
  } else if (action.key === "logout") {
    signingOut.value = true;
  }
}

function signOut(): void {
  // Frappe owns the session (04 §7); this app only sends the cashier to its
  // logout and lets the redirect land wherever the site says.
  window.location.href = "/api/method/logout";
}

const SORT_OPTIONS = [
  { key: "oldest", label: "home.sortOldest" },
  { key: "newest", label: "home.sortNewest" },
  { key: "amount", label: "home.sortAmount" },
] as const;
</script>

<template>
  <!--
    The screen is three rows: the header, the working area, and the action bar.
    `minmax(0, 1fr)` on the middle one is the whole trick — a plain `1fr` track
    refuses to shrink below its content, which is how a list stops scrolling and
    pushes the bar off the screen. The outer rows size to their content, so the
    bar is always exactly where it was.
  -->
  <div class="grid h-full grid-rows-[auto_minmax(0,1fr)_auto] bg-background">
    <PosHeader
      v-model:search="search"
      :subtitle="sectionTitle"
    />

    <!-- BR-044: no order can be created without an open shift, so say so
         instead of showing buttons that will be refused. -->
    <section
      v-if="!session.hasOpenShift"
      class="m-auto max-w-md self-center justify-self-center rounded-rpos bg-surface p-10 text-center shadow-card"
    >
      <p class="mb-2 text-lg font-semibold">
        {{ t("home.shiftRequired") }}
      </p>
      <p class="text-sm text-muted">
        {{ t("home.shiftFromDesk") }}
      </p>
    </section>

    <!--
      The working area is two columns: how to open an order, and what is open.
      The column narrows on smaller terminals rather than squeezing the floor.
    -->
    <div
      v-else
      class="grid min-h-0 grid-cols-[270px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)] 2xl:grid-cols-[320px_minmax(0,1fr)]"
    >
      <OrderTypeSidebar
        :order-types="orderTypes"
        :active="lastUsedType"
        @open="open"
      />

      <div class="grid min-h-0 grid-rows-[minmax(0,1fr)] p-5 ps-0">
        <OpenOrdersPanel
          v-model:layout="layout"
          :orders="visibleOrders"
          :loading="loadingOrders"
          :error="ordersError"
          :searching="searching"
          :scope="maySeeEveryone ? scope : null"
          @open="resume"
          @floor-plan="showFloorPlan"
          @update:scope="scope = $event"
        />
      </div>
    </div>

    <div class="relative">
      <!-- Anchored to the bar so it opens over the floor, not under it. -->
      <div
        v-if="sortOpen"
        class="absolute bottom-full end-5 z-10 mb-2 w-56 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
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

      <PosBottomBar
        :actions="bottomActions"
        @select="onAction"
      />
    </div>

    <!-- Signing out by accident mid-shift is a real annoyance at a till. -->
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
