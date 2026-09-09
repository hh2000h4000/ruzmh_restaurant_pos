<script setup lang="ts">
import { computed } from "vue";

import type { OpenOrder, OrderView } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import OpenOrderCard from "@/components/pos/OpenOrderCard.vue";
import OpenOrderRow from "@/components/pos/OpenOrderRow.vue";
import { dateOnly, formatNumber, t, timeOnly, type MessageKey } from "@/i18n";

/**
 * The floor: every order still open, in the shape the cashier asked for.
 *
 * The panel owns how the list is *shown* — rows or cards — and nothing about
 * how it is fetched or filtered. That belongs to the screen above it.
 */
const props = defineProps<{
  orders: OpenOrder[];
  loading: boolean;
  error: string | null;
  searching: boolean;
  /** `null` when this user may not see anyone else's orders. */
  scope: "mine" | "all" | null;
  /** `null` on the till screen, which only ever shows the open floor. */
  view?: OrderView | null;
  /**
   * When these rows were last fetched, if they are not live (D-080).
   *
   * Said out loud rather than shown quietly: a list of yesterday's bills is
   * useful, and a cashier who thinks it is today's will look for a sale that
   * is not on it and ring it again.
   */
  staleAt?: string | null;
  /**
   * Whether this cashier may ask for paper again (`can_reprint_receipt`).
   *
   * Passed in rather than read here, like `scope` above: the panel shows a
   * list, the screen owns who the cashier is. The server checks it again.
   */
  mayReprint?: boolean;
  /** `null` until somebody searched past today; then, what came back (`D-152`). */
  older?: OpenOrder[] | null;
  searchingOlder?: boolean;
  /** How many bills are carried, for the switch to say so (`D-164`). */
  carriedCount?: number;
  /** Whether the open list currently also holds them (`D-168`). */
  includeCarried?: boolean;
}>();

const emit = defineEmits<{
  searchOlder: [];
  open: [order: OpenOrder];
  reprint: [order: OpenOrder];
  floorPlan: [];
  "update:scope": [scope: "mine" | "all"];
  "update:view": [view: OrderView];
  "update:includeCarried": [include: boolean];
}>();

const layout = defineModel<"list" | "grid">("layout", { default: "list" });

/**
 * Finding one order, and choosing what comes first.
 *
 * Both lived in the till screen's chrome — a search box in the header, a sort
 * sheet above the bottom bar. That screen is gone (D-055) and neither belonged
 * to it: they act on *this list*, so they live on it, beside the controls that
 * already do.
 */
const search = defineModel<string>("search", { default: "" });
// Newest first, the same as the composable that usually supplies it: a default
// written twice is a default the two copies disagree about.
const sort = defineModel<"oldest" | "newest" | "amount">("sort", { default: "newest" });

const SORTS: { key: "oldest" | "newest" | "amount"; label: MessageKey }[] = [
  { key: "newest", label: "home.sortNewest" },
  { key: "oldest", label: "home.sortOldest" },
  { key: "amount", label: "home.sortAmount" },
];

/**
 * The four questions this pane can ask the server (D-042).
 *
 * Tabs, not a filter over what is already here: today's closed orders were
 * never fetched, so switching is a new request. Ordered from the one a cashier
 * lives in to the one they visit.
 */
/**
 * What an empty list means, in the words of the tab that is empty.
 *
 * One message served all four, so a till with nothing refunded today read
 * "no open orders — choose an order type to start": advice for a different
 * screen, under a heading it does not belong to. A wrong sentence is not much
 * better than the blank one `D-074` is about.
 */
const EMPTY: Record<OrderView, MessageKey> = {
  open: "home.openOrdersEmpty",
  closed: "orders.emptyClosed",
  returned: "orders.emptyReturned",
  all: "orders.emptyAll",
};

/**
 * **Every tab is a status** (`D-146`, `D-168`): open, closed today, refunded
 * today, everything. A bill's *age* is not on this axis — a carried bill is an
 * open bill — so it is a switch inside the open view rather than a fifth tab.
 *
 * It was a fifth tab for a day. The user pushed back: an open bill belongs with
 * the open bills, and a till does not need more tabs. The research agreed —
 * Toast keeps unpaid checks from the previous day in the Open tab and separates
 * them by sort and search, not by a tab — and so did our own `D-146`, which
 * this had quietly broken.
 */
const VIEWS: { key: OrderView; label: MessageKey }[] = [
  { key: "open", label: "orders.viewOpen" },
  { key: "closed", label: "orders.viewClosed" },
  // FR-9, D-070 — the refunds were only visible inside the bill they came from.
  { key: "returned", label: "orders.viewReturned" },
  { key: "all", label: "orders.viewAll" },
];

/**
 * The switch wears its count (`D-164`), and appears only when there is one.
 *
 * **Without the number it hides the backlog as well as the old mixed list did.**
 * A shop carrying three hundred bills would learn it by turning on a switch
 * nobody has a reason to touch — which is how the backlog grew unseen.
 *
 * With nothing carried the switch is not drawn at all: an empty floor is the
 * whole answer, and a control that is always there with "(0)" beside it stops
 * being read.
 */
const showCarriedSwitch = computed(() => props.view === "open" && Boolean(props.carriedCount));
</script>

<template>
  <!--
    Two rows: the toolbar sizes to its content, the list takes what is left and
    scrolls inside it. Both rows are declared here rather than left to flex, so
    the list cannot grow the panel and take the page with it.
  -->
  <section
    class="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] rounded-rpos bg-surface p-6 shadow-card"
  >
    <div>
      <div class="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 class="text-[25px] font-medium leading-tight text-content">
            {{ t("home.openOrders") }}
          </h2>
          <p class="mt-1.5 text-[13.5px] text-subtle">
            <span class="rpos-numeric">{{ formatNumber(orders.length) }}</span>
            {{ t("home.openOrdersUnit") }}
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2.5">
          <!-- Only for someone who may see the whole floor. The backend enforces
               the same rule regardless (FR-12.3). -->
          <div
            v-if="scope"
            class="flex rounded-full bg-background p-1"
            role="group"
          >
            <button
              v-for="option in (['mine', 'all'] as const)"
              :key="option"
              type="button"
              class="min-h-tap rounded-full px-6 text-xs font-medium transition-colors duration-100 ease-rpos"
              :class="scope === option ? 'bg-primary text-primary-contrast' : 'text-muted'"
              :aria-pressed="scope === option"
              @click="emit('update:scope', option)"
            >
              {{ option === "mine" ? t("home.scopeMine") : t("home.scopeAll") }}
            </button>
          </div>

          <div class="flex h-[58px] w-[124px] rounded-[15px] bg-background p-[5px]">
            <button
              v-for="option in (['grid', 'list'] as const)"
              :key="option"
              type="button"
              class="grid h-12 flex-1 place-items-center rounded-xl transition-colors duration-100 ease-rpos"
              :class="layout === option ? 'bg-primary text-primary-contrast shadow-card' : 'text-muted'"
              :aria-pressed="layout === option"
              :aria-label="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
              :title="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
              @click="layout = option"
            >
              <AppIcon
                :name="option"
                :size="20"
              />
            </button>
          </div>
        </div>
      </div>

      <div class="mb-4 flex flex-wrap items-center gap-2.5">
        <label class="flex h-14 min-w-[220px] flex-1 items-center gap-2.5 rounded-[15px] border border-line bg-background px-[18px]">
          <AppIcon
            name="search"
            :size="20"
            class="shrink-0 text-muted"
          />
          <input
            v-model="search"
            type="search"
            class="h-full w-full bg-transparent text-[15px] placeholder:text-muted"
            :placeholder="t('home.search')"
            :aria-label="t('home.search')"
          >
        </label>

        <select
          v-model="sort"
          class="h-14 w-[168px] shrink-0 rounded-[15px] border border-line bg-background px-[18px] text-xs text-content"
          :aria-label="t('home.sort')"
        >
          <option
            v-for="option in SORTS"
            :key="option.key"
            :value="option.key"
          >
            {{ t(option.label) }}
          </option>
        </select>
      </div>

      <!-- Which orders, asked of the server. Only where more than the open
           floor is on offer (D-042). -->
      <div
        v-if="view"
        class="mb-4 flex flex-wrap gap-2"
        role="tablist"
      >
        <button
          v-for="option in VIEWS"
          :key="option.key"
          type="button"
          role="tab"
          class="h-[50px] rounded-[14px] border px-6 text-xs font-medium transition-colors duration-100 ease-rpos"
          :class="
            view === option.key
              ? 'border-primary bg-primary text-primary-contrast'
              : 'border-line bg-background text-subtle hover:text-content'
          "
          :aria-selected="view === option.key"
          @click="emit('update:view', option.key)"
        >
          {{ t(option.label) }}
        </button>
      </div>

      <!-- Bills whose business day has ended: asked for, inside the list they
           belong to (`D-168`). -->
      <label
        v-if="showCarriedSwitch"
        class="mb-4 flex w-fit cursor-pointer items-center gap-2.5 rounded-[14px] border border-line bg-background px-4 py-2.5 text-xs text-subtle transition-colors duration-100 ease-rpos hover:text-content"
      >
        <input
          type="checkbox"
          :checked="includeCarried"
          class="h-4 w-4 accent-primary"
          @change="emit('update:includeCarried', ($event.target as HTMLInputElement).checked)"
        >
        {{ t("orders.showCarried", { count: formatNumber(carriedCount ?? 0) }) }}
      </label>

      <!-- D-080 — the last answer the server gave, with its age on it. -->
      <p
        v-if="staleAt"
        role="status"
        class="mb-3 flex items-center gap-2 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
      >
        <AppIcon
          name="hourglass"
          :size="18"
        />
        {{ t("orders.stale", { when: `${dateOnly(staleAt)} ${timeOnly(staleAt)}` }) }}
      </p>

      <p
        v-if="error"
        role="alert"
        class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ error }}
      </p>

      <!--
        `D-152` — the door out of today, and only when somebody is at it.

        The tabs are the day; a bill from last week is a different question and
        a different query, with a window and a ceiling on it. Offering it before
        anybody has typed would be a button that reaches over months on a
        screen whose whole job is the next customer.
      -->
      <p
        v-if="older"
        role="status"
        class="mb-3 flex items-center justify-between gap-2 rounded-rpos bg-background p-3 text-sm"
      >
        <span class="flex items-center gap-2 text-muted">
          <AppIcon
            name="search"
            :size="18"
          />
          {{ t("orders.olderFound", { count: formatNumber(older.length) }) }}
        </span>
        <button
          type="button"
          class="shrink-0 font-semibold text-primary underline"
          @click="search = ''"
        >
          {{ t("action.back") }}
        </button>
      </p>
    </div>

    <div class="min-h-0 overflow-y-auto">
      <div
        v-if="orders.length && layout === 'list'"
        class="flex flex-col gap-3.5"
      >
        <OpenOrderRow
          v-for="order in orders"
          :key="order.credit_note ?? order.name"
          :order="order"
          :may-reprint="mayReprint"
          @open="emit('open', order)"
          @reprint="emit('reprint', order)"
          @floor-plan="emit('floorPlan')"
        />
      </div>

      <!-- The same orders and the same fields, stacked instead of spread. -->
      <div
        v-else-if="orders.length"
        class="grid grid-cols-1 gap-3.5 md:grid-cols-2 2xl:grid-cols-3"
      >
        <OpenOrderCard
          v-for="order in orders"
          :key="order.credit_note ?? order.name"
          :order="order"
          :may-reprint="mayReprint"
          @open="emit('open', order)"
          @reprint="emit('reprint', order)"
          @floor-plan="emit('floorPlan')"
        />
      </div>

      <div
        v-else-if="!loading"
        class="grid place-items-center px-6 py-20 text-center"
      >
        <span class="mb-3 text-muted opacity-40">
          <AppIcon
            name="receipt"
            :size="48"
          />
        </span>
        <p class="text-muted">
          {{ searching ? t("home.searchEmpty") : t(EMPTY[view ?? "open"]) }}
        </p>

        <!-- Nothing today under that name — so offer the only place left to
             look, rather than leaving the cashier at a dead end (`D-074`). -->
        <button
          v-if="searching && !older"
          type="button"
          class="min-h-tap mt-4 rounded-rpos bg-primary px-6 font-bold text-primary-contrast disabled:opacity-50"
          :disabled="searchingOlder"
          @click="emit('searchOlder')"
        >
          {{ searchingOlder ? t("common.loading") : t("orders.searchOlder") }}
        </button>
      </div>
    </div>
  </section>
</template>
