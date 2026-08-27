<script setup lang="ts">
import type { OpenOrder } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { dateOnly, formatNumber, pick, t, timeOnly } from "@/i18n";

/**
 * One open order, as a row.
 *
 * Every column is a value over its label, which is how a stack of bills is
 * actually read: the eye lands on the number and the label explains it. 108px
 * tall, per the layout specification — a row that fits three lines of small
 * text is a row nobody can hit.
 */
defineProps<{ order: OpenOrder }>();
defineEmits<{ open: [] }>();

/**
 * Status colour follows the order lifecycle and is never the only signal: the
 * pill always spells the status out (06 §Accessibility).
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
</script>

<template>
  <button
    type="button"
    class="flex min-h-[108px] w-full items-center gap-4 rounded-rpos border border-line bg-surface px-5 text-start shadow-card transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-lift"
    @click="$emit('open')"
  >
    <div class="flex min-w-0 flex-1 items-center gap-3">
      <span
        class="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-full bg-primary/10 text-primary"
        aria-hidden="true"
      >
        <AppIcon name="user" />
      </span>
      <div class="min-w-0">
        <p class="truncate font-semibold">
          {{ order.cashier_name }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ t("card.cashier") }}
        </p>
      </div>
    </div>

    <div class="hidden min-w-0 flex-1 md:block">
      <p class="truncate font-semibold">
        {{ whereLabel(order) }}
      </p>
      <p class="rpos-numeric truncate text-sm text-muted">
        {{ order.name }}
      </p>
    </div>

    <div class="hidden flex-1 lg:block">
      <p class="rpos-numeric font-semibold">
        {{ dateOnly(order.opened_at) }}
      </p>
      <p class="rpos-numeric text-sm text-muted">
        {{ timeOnly(order.opened_at) }}
      </p>
    </div>

    <div class="shrink-0 text-center">
      <span
        class="rpos-numeric mx-auto grid h-9 w-9 place-items-center rounded-full bg-primary/10 font-semibold text-primary"
      >{{ formatNumber(order.item_count) }}</span>
      <p class="mt-1 text-sm text-muted">
        {{ t("card.itemCount") }}
      </p>
    </div>

    <div class="shrink-0">
      <p class="rpos-numeric text-[22px] font-bold leading-tight text-primary">
        {{ formatNumber(order.total_amount, 2) }}
      </p>
      <p class="text-sm text-muted">
        {{ t("card.amount") }}
      </p>
    </div>

    <span
      class="shrink-0 rounded-full px-3 py-1.5 text-sm font-medium"
      :class="STATUS_CLASS[order.status]"
    >
      {{ t(`status.${order.status}`) }}
    </span>
  </button>
</template>
