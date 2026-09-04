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
 * **The order number is never truncated** (D-060). It is the one value on the
 * row a cashier reads *out* — to a customer on the phone, to a manager tracing
 * a refund — and half of it is worth nothing. So it takes the width it needs
 * and the columns that can lose a few characters, do.
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
  // History, since the orders pane can ask for today's closed bills (D-042).
  closed: "text-order-closed",
  cancelled: "text-order-cancelled",
  // D-075 — sold on this device, not yet on the server. Shares the colour the
  // rest of the app already uses for work waiting to sync.
  queued: "text-status-cleaning",
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
    class="relative flex min-h-[88px] items-center gap-3 rounded-rpos border border-line bg-surface px-4 shadow-card transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-lift"
  >
    <!-- The whole row opens the order; the menu sits above it. -->
    <button
      type="button"
      class="absolute inset-0 rounded-rpos"
      :aria-label="t('card.openOrder')"
      @click="emit('open')"
    />

    <div class="shrink-0">
      <p class="rpos-numeric text-[20px] font-bold leading-tight text-primary">
        {{ formatNumber(order.total_amount, 2) }}
      </p>
      <!-- FR-9, D-070 — a bill money went back out of says so where the money
           is read. Without it a refunded sale looked exactly like a kept one. -->
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

    <div class="shrink-0 text-center">
      <span
        class="rpos-numeric mx-auto grid h-8 w-8 place-items-center rounded-full bg-primary/10 font-bold text-primary"
      >{{ formatNumber(order.item_count) }}</span>
      <p class="mt-1 text-sm text-muted">
        {{ t("card.itemCount") }}
      </p>
    </div>

    <!-- A date is a fixed width; giving it a share of the leftover space only
         took room from the number beside it. -->
    <div class="hidden shrink-0 lg:block">
      <p class="rpos-numeric font-bold">
        {{ dateOnly(order.opened_at) }}
      </p>
      <p class="rpos-numeric text-sm text-muted">
        {{ timeOnly(order.opened_at) }}
      </p>
    </div>

    <!-- `shrink-0`, and no `truncate`: a half-read order number is no use to
         anybody, so this column takes what it needs (D-060). -->
    <div class="hidden shrink-0 md:block">
      <p class="rpos-numeric whitespace-nowrap font-bold">
        {{ order.name }}
      </p>
      <p class="text-sm text-muted">
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

    <!-- A draft says so, like every other status.

         It used to be left blank, on the reasoning that every bill on this
         screen is a draft until it moves. That held while the screen showed one
         kind of bill. It does not on a mixed list: one row reads "active" and
         the row under it reads nothing, and a blank in a column every other row
         fills is read as missing data rather than as a state. The user asked
         what the difference between the two tabs was, and the answer was on the
         screen the whole time — invisible. -->
    <div class="shrink-0">
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

    <!-- The avatar circle went here (D-060). It was `aria-hidden` decoration
         beside the name it decorated, and it cost fifty pixels the order number
         needed. -->
    <div class="min-w-0 flex-1 text-end">
      <p class="truncate font-bold">
        {{ order.cashier_name }}
      </p>
      <p class="truncate text-sm text-muted">
        {{ t("card.cashier") }}
      </p>
    </div>

    <button
      type="button"
      class="relative z-10 grid h-10 w-10 shrink-0 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-background"
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
