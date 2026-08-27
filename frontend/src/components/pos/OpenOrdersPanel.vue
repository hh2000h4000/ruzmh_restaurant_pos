<script setup lang="ts">
import type { OpenOrder } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import OpenOrderRow from "@/components/pos/OpenOrderRow.vue";
import { formatNumber, pick, t, tn } from "@/i18n";

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
}>();

const emit = defineEmits<{
  open: [order: OpenOrder];
  floorPlan: [];
  "update:scope": [scope: "mine" | "all"];
}>();

const view = defineModel<"list" | "grid">("view", { default: "list" });

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
</script>

<template>
  <section class="flex min-w-0 flex-1 flex-col rounded-rpos bg-surface p-6 shadow-card">
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
            :class="view === option ? 'bg-primary text-primary-contrast shadow-card' : 'text-muted'"
            :aria-pressed="view === option"
            :aria-label="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
            :title="option === 'grid' ? t('home.viewGrid') : t('home.viewList')"
            @click="view = option"
          >
            <AppIcon
              :name="option"
              :size="22"
            />
          </button>
        </div>
      </div>
    </div>

    <p
      v-if="error"
      role="alert"
      class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ error }}
    </p>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <div
        v-if="orders.length && view === 'list'"
        class="flex flex-col gap-3.5"
      >
        <OpenOrderRow
          v-for="order in orders"
          :key="order.name"
          :order="order"
          @open="emit('open', order)"
          @floor-plan="emit('floorPlan')"
        />
      </div>

      <!-- The same orders, when the floor is read by table rather than by bill. -->
      <div
        v-else-if="orders.length"
        class="grid grid-cols-1 gap-3.5 md:grid-cols-2 2xl:grid-cols-3"
      >
        <button
          v-for="order in orders"
          :key="order.name"
          type="button"
          class="flex flex-col gap-3 rounded-rpos border border-line bg-surface p-5 text-start shadow-card transition duration-200 ease-rpos hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lift"
          @click="emit('open', order)"
        >
          <div class="flex items-start justify-between gap-2">
            <span class="truncate text-lg font-bold">{{ whereLabel(order) }}</span>
            <span
              class="shrink-0 rounded-full px-3 py-1 text-sm font-medium"
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
              <p class="rpos-numeric truncate text-sm text-muted">
                {{ order.name }}
              </p>
              <p class="truncate text-sm text-muted">
                {{ order.cashier_name }}
              </p>
            </div>
            <span class="rpos-numeric shrink-0 text-[22px] font-bold text-primary">
              {{ formatNumber(order.total_amount, 2) }}
            </span>
          </div>
        </button>
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
          {{ searching ? t("home.searchEmpty") : t("home.openOrdersEmpty") }}
        </p>
      </div>
    </div>
  </section>
</template>
