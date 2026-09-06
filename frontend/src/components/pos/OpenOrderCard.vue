<script setup lang="ts">
import { computed, ref } from "vue";

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
const props = defineProps<{
  order: OpenOrder;
  /** UX only — the server checks `can_reprint_receipt` again (`CLAUDE.md` §5.4). */
  mayReprint?: boolean;
}>();
const emit = defineEmits<{ open: []; floorPlan: []; reprint: [] }>();

/** What this card would put on paper: a refund's credit note, or the sale. */
const receipt = computed<string | null>(
  () => props.order.credit_note ?? props.order.sales_invoice ?? null,
);

/**
 * The moment this row is about (`D-146`).
 *
 * An open bill is dated by when it opened — that is what the cashier is
 * waiting on. A closed one, and a refund, are dated by when they happened;
 * showing the opening time under a tab called "today" is how a bill paid at
 * one in the morning reads as yesterday's.
 */
const happenedAt = computed(() => props.order.closed_at ?? props.order.opened_at);

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
  // D-075 — sold on this device, not yet on the server. Shares the colour the
  // rest of the app already uses for work waiting to sync.
  queued: "text-status-cleaning",
};

function whereLabel(order: OpenOrder): string {
  // A refund says which bill it reverses, because that is the only thing about
  // it a cashier needs to place it (`D-143`). The table it was eaten at is the
  // sale's business, and by now somebody else is sitting there.
  if (order.is_return) {
    return t("ret.against", { number: formatNumber(order.returns_daily_number ?? 0) });
  }

  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

/** The same three entries as the row's, for the same reasons (`D-145`). */
function choose(where: "order" | "floor" | "reprint"): void {
  menuOpen.value = false;
  if (where === "order") emit("open");
  else if (where === "reprint") emit("reprint");
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
        <!-- A draft says so, like every other status.

         It used to be left blank, on the reasoning that every bill on this
         screen is a draft until it moves. That held while the screen showed one
         kind of bill. It does not on a mixed list: one row reads "active" and
         the row under it reads nothing, and a blank in a column every other row
         fills is read as missing data rather than as a state. The user asked
         what the difference between the two tabs was, and the answer was on the
         screen the whole time — invisible. -->
        <div class="text-end">
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
          :aria-label="t('card.options')"
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
        <p
          class="rpos-numeric text-[22px] font-bold leading-tight"
          :class="order.is_return ? 'text-danger' : 'text-primary'"
        >
          {{ formatNumber(order.total_amount, 2) }}
        </p>
        <!-- FR-9, D-070 — the same signal as the row: a refunded bill reads
             differently from a kept one, where the money is read. -->
        <p
          v-if="order.is_return"
          class="text-sm text-danger"
        >
          {{ t("ret.rowLabel") }}
        </p>
        <p
          v-else-if="order.returned_amount"
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
          {{ dateOnly(happenedAt) }}
        </p>
        <p class="rpos-numeric text-sm text-muted">
          {{ timeOnly(happenedAt) }}
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
      <!-- FR-7.5 — the receipt the customer holds, again. -->
      <button
        v-if="receipt && mayReprint"
        type="button"
        class="block w-full px-4 text-start text-sm transition duration-200 ease-rpos hover:bg-background"
        @click.stop="choose('reprint')"
      >
        {{ t("print.receiptAgain") }}
      </button>
    </div>
  </div>
</template>
