<script setup lang="ts">
import { computed, ref } from "vue";

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
const props = defineProps<{
  order: OpenOrder;
  /** UX only — the server checks `can_reprint_receipt` again (`CLAUDE.md` §5.4). */
  mayReprint?: boolean;
}>();
const emit = defineEmits<{ open: []; floorPlan: []; reprint: [] }>();

/**
 * What this row would put on paper, if anything (`D-145`).
 *
 * A refund row **is** its credit note; a closed row is its sale. An open bill
 * has no invoice yet — there is nothing to reprint until it is paid for.
 */
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
  // A refund says which bill it reverses, because that is the only thing about
  // it a cashier needs to place it (`D-143`). The table it was eaten at is the
  // sale's business, and by now somebody else is sitting there.
  if (order.is_return) {
    return t("ret.against", { number: formatNumber(order.returns_daily_number ?? 0) });
  }

  if (order.table_number) return t("card.table", { number: order.table_number });
  return pick(order.order_type_title_ar, order.order_type_title);
}

/**
 * Where the cashier goes — and the one thing this row can do (`D-145`).
 *
 * `D-033` kept actions off the **bottom bar**, because a control acting on "the
 * highlighted card" needs a selection mode and at a busy till that is how a
 * refund lands on the wrong bill. This menu belongs to one row and opens from
 * it, so there is no highlight to be wrong about — and a reprint is the one
 * request that has no other home: a refund is a row here and nowhere else.
 * It changes no document; it asks for paper.
 */
function choose(where: "order" | "floor" | "reprint"): void {
  menuOpen.value = false;
  if (where === "order") emit("open");
  else if (where === "reprint") emit("reprint");
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
      <!-- A refund row carries its own figure, already negative (`D-143`);
           a sale carries the sale's. -->
      <p
        class="rpos-numeric text-[20px] font-bold leading-tight"
        :class="order.is_return ? 'text-danger' : 'text-primary'"
      >
        {{ formatNumber(order.total_amount, 2) }}
      </p>
      <!-- FR-9, D-070 — a bill money went back out of says so where the money
           is read. Without it a refunded sale looked exactly like a kept one.
           On a refund row the figure above already is the refund. -->
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
        {{ dateOnly(happenedAt) }}
      </p>
      <p class="rpos-numeric text-sm text-muted">
        {{ timeOnly(happenedAt) }}
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
      :aria-label="t('card.options')"
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
      <!-- FR-7.5 — the receipt the customer holds, again. A refund's own
           credit note when this row is one (`D-143`). -->
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
