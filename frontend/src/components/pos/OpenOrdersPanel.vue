<script setup lang="ts">
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
defineProps<{
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
}>();

const emit = defineEmits<{
  open: [order: OpenOrder];
  reprint: [order: OpenOrder];
  floorPlan: [];
  "update:scope": [scope: "mine" | "all"];
  "update:view": [view: OrderView];
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
const sort = defineModel<"oldest" | "newest" | "amount">("sort", { default: "oldest" });

const SORTS: { key: "oldest" | "newest" | "amount"; label: MessageKey }[] = [
  { key: "oldest", label: "home.sortOldest" },
  { key: "newest", label: "home.sortNewest" },
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

const VIEWS: { key: OrderView; label: MessageKey }[] = [
  { key: "open", label: "orders.viewOpen" },
  { key: "closed", label: "orders.viewClosed" },
  // FR-9, D-070 — the refunds were only visible inside the bill they came from.
  { key: "returned", label: "orders.viewReturned" },
  { key: "all", label: "orders.viewAll" },
];
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
          <h2 class="flex items-center gap-2 text-2xl font-bold">
            <AppIcon
              name="document"
              :size="26"
            />
            {{ t("home.openOrders") }}
          </h2>
          <p class="mt-1 text-base text-muted">
            <span class="rpos-numeric font-bold text-primary">{{ formatNumber(orders.length) }}</span>
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
              class="min-h-tap rounded-full px-6 text-sm font-semibold transition duration-200 ease-rpos"
              :class="scope === option ? 'bg-primary text-primary-contrast' : 'text-muted'"
              :aria-pressed="scope === option"
              @click="emit('update:scope', option)"
            >
              {{ option === "mine" ? t("home.scopeMine") : t("home.scopeAll") }}
            </button>
          </div>

          <div class="flex h-[50px] w-[120px] rounded-rpos bg-background p-1">
            <button
              v-for="option in (['grid', 'list'] as const)"
              :key="option"
              type="button"
              class="grid flex-1 place-items-center rounded-[0.75rem] transition duration-200 ease-rpos"
              :class="layout === option ? 'bg-primary text-primary-contrast shadow-card' : 'text-muted'"
              :aria-pressed="layout === option"
              :aria-label="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
              :title="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
              @click="layout = option"
            >
              <AppIcon
                :name="option"
                :size="22"
              />
            </button>
          </div>
        </div>
      </div>

      <div class="mb-4 flex flex-wrap items-center gap-2.5">
        <label class="flex min-w-[220px] flex-1 items-center gap-2 rounded-rpos bg-background px-3">
          <AppIcon
            name="search"
            :size="20"
            class="shrink-0 text-muted"
          />
          <input
            v-model="search"
            type="search"
            class="min-h-tap w-full bg-transparent"
            :placeholder="t('home.search')"
            :aria-label="t('home.search')"
          >
        </label>

        <select
          v-model="sort"
          class="min-h-tap shrink-0 rounded-rpos bg-background px-3 text-sm font-semibold text-muted"
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
          class="min-h-tap rounded-rpos px-5 text-sm font-semibold transition duration-200 ease-rpos"
          :class="
            view === option.key
              ? 'bg-primary text-primary-contrast shadow-card'
              : 'bg-background text-muted hover:text-content'
          "
          :aria-selected="view === option.key"
          @click="emit('update:view', option.key)"
        >
          {{ t(option.label) }}
        </button>
      </div>

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
      </div>
    </div>
  </section>
</template>
