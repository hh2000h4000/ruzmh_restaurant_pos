<script setup lang="ts">
import { ref } from "vue";

import type { OpenOrder } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { dateOnly, formatNumber, pick, t, timeOnly } from "@/i18n";

/**
 * One open order, as a row.
 *
 * **Every column is a value over its label.** That is the whole grammar of the
 * row: the eye lands on the number and the small grey line underneath says what
 * it was. A pill for one column and a label for the rest would be two languages
 * in one row.
 *
 * **The amount comes first in reading order** — the right in Arabic, the left
 * in English — because it is the one figure a cashier looks for. Who opened the
 * order comes last. The order flips with the language on its own: the row is a
 * plain flex line, and direction is set on `<html>`.
 *
 * 108px tall, evenly distributed, per the reference layout.
 */
const props = defineProps<{ order: OpenOrder }>();
const emit = defineEmits<{ open: []; floorPlan: [] }>();

const menuOpen = ref(false);

/**
 * Status colour follows the order lifecycle and is never the only signal: the
 * status is written out, in words, in every language the app ships
 * (06 §Accessibility).
 */
const STATUS_TEXT: Record<OpenOrder["status"], string> = {
  draft: "text-order-draft",
  active: "text-order-active",
  in_kitchen: "text-order-in_kitchen",
  pending_payment: "text-order-pending_payment",
};

function whereLabel(order: OpenOrder): string {
  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

/**
 * The menu is navigation only (D-033).
 *
 * A control that acts on "the highlighted order" needs a selection mode, and at
 * a busy till that is how an action lands on the wrong bill. Both entries here
 * take the cashier somewhere; neither changes anything.
 */
function choose(where: "order" | "floor"): void {
  menuOpen.value = false;
  if (where === "order") emit("open");
  else emit("floorPlan");
}
</script>

<template>
  <div
    class="relative flex min-h-[108px] items-center gap-4 rounded-rpos border border-line bg-surface px-5 shadow-card transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-lift"
  >
    <!-- The whole row opens the order; the menu sits above it. -->
    <button
      type="button"
      class="absolute inset-0 rounded-rpos"
      :aria-label="t('card.openOrder')"
      @click="emit('open')"
    />

    <div class="shrink-0">
      <p class="rpos-numeric text-[22px] font-bold leading-tight text-primary">
        {{ formatNumber(order.total_amount, 2) }}
      </p>
      <p class="text-sm text-muted">
        {{ t("card.amount") }}
      </p>
    </div>

    <div class="shrink-0 text-center">
      <span
        class="rpos-numeric mx-auto grid h-9 w-9 place-items-center rounded-full bg-primary/10 font-bold text-primary"
      >{{ formatNumber(order.item_count) }}</span>
      <p class="mt-1 text-sm text-muted">
        {{ t("card.itemCount") }}
      </p>
    </div>

    <div class="hidden flex-1 lg:block">
      <p class="rpos-numeric font-bold">
        {{ dateOnly(order.opened_at) }}
      </p>
      <p class="rpos-numeric text-sm text-muted">
        {{ timeOnly(order.opened_at) }}
      </p>
    </div>

    <div class="hidden min-w-0 flex-1 md:block">
      <p class="rpos-numeric truncate font-bold">
        {{ order.name }}
      </p>
      <p class="truncate text-sm text-muted">
        {{ t("card.number") }}
      </p>
    </div>

    <div class="hidden min-w-0 flex-1 sm:block">
      <p class="truncate font-bold">
        {{ whereLabel(order) }}
      </p>
      <p class="truncate text-sm text-muted">
        {{ t("card.type") }}
      </p>
    </div>

    <!-- Draft says nothing: every order on this screen is one until it moves.
         The column appears when the status is worth reading. -->
    <div
      v-if="order.status !== 'draft'"
      class="shrink-0"
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

    <div class="flex min-w-0 flex-1 items-center justify-end gap-3">
      <div class="min-w-0 text-end">
        <p class="truncate font-bold">
          {{ order.cashier_name }}
        </p>
        <p class="truncate text-sm text-muted">
          {{ t("card.cashier") }}
        </p>
      </div>
      <span
        class="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-full bg-primary/10 text-primary"
        aria-hidden="true"
      >
        <AppIcon name="user" />
      </span>
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

    <div
      v-if="menuOpen"
      class="absolute top-full end-0 z-20 mt-1 w-56 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
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
