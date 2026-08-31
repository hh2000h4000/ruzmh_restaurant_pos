<script setup lang="ts">
import { ref } from "vue";

import type { OpenOrder } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { dateOnly, formatNumber, pick, t, timeOnly } from "@/i18n";

/**
 * One open order, as a card.
 *
 * The same order as `OpenOrderRow`, carrying **the same fields under the same
 * labels** — amount, items, date, number, cashier — only stacked instead of
 * spread. Two views of one list that disagree about what an order is would
 * make the toggle a trap rather than a preference.
 */
const props = defineProps<{ order: OpenOrder }>();
const emit = defineEmits<{ open: []; floorPlan: [] }>();

const menuOpen = ref(false);

/** Colour follows the lifecycle, and the status is always written out. */
const STATUS_TEXT: Record<OpenOrder["status"], string> = {
  draft: "text-order-draft",
  active: "text-order-active",
  in_kitchen: "text-order-in_kitchen",
  pending_payment: "text-order-pending_payment",
  // History, since the orders pane can ask for today's closed bills (D-042).
  closed: "text-order-closed",
  cancelled: "text-order-cancelled",
};

function whereLabel(order: OpenOrder): string {
  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

/** Navigation only, like the row's (D-033). */
function choose(where: "order" | "floor"): void {
  menuOpen.value = false;
  if (where === "order") emit("open");
  else emit("floorPlan");
}
</script>

<template>
  <div
    class="relative flex flex-col gap-4 rounded-rpos border border-line bg-surface p-5 shadow-card transition duration-200 ease-rpos hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lift"
  >
    <button
      type="button"
      class="absolute inset-0 rounded-rpos"
      :aria-label="t('card.openOrder')"
      @click="emit('open')"
    />

    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <p class="truncate text-lg font-bold">
          {{ whereLabel(order) }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ t("card.type") }}
        </p>
      </div>

      <div class="flex shrink-0 items-start gap-1">
        <!-- Draft says nothing: every order here is one until it moves. -->
        <div
          v-if="order.status !== 'draft'"
          class="text-end"
        >
          <p
            class="font-bold"
            :class="STATUS_TEXT[order.status]"
          >
            {{ t(`status.${order.status}`) }}
          </p>
          <p class="text-sm text-muted">
            {{ t("card.status") }}
          </p>
        </div>

        <button
          type="button"
          class="relative z-10 grid h-11 w-11 shrink-0 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-background"
          :aria-label="t('card.openOrder')"
          :aria-expanded="menuOpen"
          @click.stop="menuOpen = !menuOpen"
        >
          <AppIcon
            name="more"
            :size="22"
          />
        </button>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div>
        <p class="rpos-numeric text-[22px] font-bold leading-tight text-primary">
          {{ formatNumber(order.total_amount, 2) }}
        </p>
        <!-- FR-9, D-070 — the same signal as the row: a refunded bill reads
             differently from a kept one, where the money is read. -->
        <p
          v-if="order.returned_amount"
          class="rpos-numeric text-sm font-semibold text-danger"
        >
          −{{ formatNumber(order.returned_amount, 2) }}
        </p>
        <p
          v-else
          class="text-sm text-muted"
        >
          {{ t("card.amount") }}
        </p>
      </div>

      <div>
        <span
          class="rpos-numeric grid h-9 w-9 place-items-center rounded-full bg-primary/10 font-bold text-primary"
        >{{ formatNumber(order.item_count) }}</span>
        <p class="mt-1 text-sm text-muted">
          {{ t("card.itemCount") }}
        </p>
      </div>

      <div>
        <p class="rpos-numeric font-bold">
          {{ dateOnly(order.opened_at) }}
        </p>
        <p class="rpos-numeric text-sm text-muted">
          {{ timeOnly(order.opened_at) }}
        </p>
      </div>

      <div class="min-w-0">
        <p class="rpos-numeric truncate font-bold">
          {{ order.name }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ t("card.number") }}
        </p>
      </div>
    </div>

    <div class="flex items-center gap-3 border-t border-line pt-4">
      <span
        class="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-full bg-primary/10 text-primary"
        aria-hidden="true"
      >
        <AppIcon name="user" />
      </span>
      <div class="min-w-0">
        <p class="truncate font-bold">
          {{ order.cashier_name }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ t("card.cashier") }}
        </p>
      </div>
    </div>

    <div
      v-if="menuOpen"
      class="absolute top-16 end-4 z-20 w-56 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
    >
      <button
        type="button"
        class="block w-full px-4 text-start text-sm transition duration-200 ease-rpos hover:bg-background"
        @click.stop="choose('order')"
      >
        {{ t("card.openOrder") }}
      </button>
      <button
        v-if="props.order.table_number"
        type="button"
        class="block w-full px-4 text-start text-sm transition duration-200 ease-rpos hover:bg-background"
        @click.stop="choose('floor')"
      >
        {{ t("card.goToTable") }}
      </button>
    </div>
  </div>
</template>
