<script setup lang="ts">
import { computed, ref } from "vue";

import type { OpenOrder } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { dateOnly, formatNumber, pick, t, timeOnly } from "@/i18n";

/**
 * One order, as a row.
 *
 * **Every column is a value over its label**, and the two are never the same
 * weight (`D-159`). That is the whole grammar: the eye lands on the figure and
 * the small grey word underneath says what it was. Drawn at one size, as this
 * was, a row is eight equally loud things and the cashier reads all of them to
 * find one — which is what the user meant by *"الخط كبير ويحتاج إعادة تحجيم"*.
 *
 * **Three voices, not two:** the value in ink, content beside it — a status, an
 * order type — in `subtle`, and the caption in `muted` at `text-label`. Captions
 * are the one thing on the till allowed under 14px: they are read once while
 * learning the screen and never again.
 *
 * **The amount comes first in reading order** — the right in Arabic, the left in
 * English — because it is the figure a cashier looks for. The order flips with
 * the language on its own: the row is a plain flex line and direction is set on
 * `<html>`.
 *
 * **The order number is never truncated** (`D-060`). It is the one value a
 * cashier reads *out* — to a customer on the phone, to a manager tracing a
 * refund — and half of it is worth nothing.
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
 * The document number this row carries (`D-151`).
 *
 * A refund has no `Restaurant Order` of its own — it is a credit note against
 * one — so the row was drawing the **sale's** number, and two rows on the
 * returns tab read as the same document. Its own number is the credit note's.
 */
const documentNumber = computed(() =>
  props.order.is_return ? (props.order.credit_note ?? props.order.name) : props.order.name,
);

/**
 * The short number the customer is told (`FR-2.10`), asked for by the user.
 *
 * **It was on no row at all**, and it is the only number here that gets spoken:
 * a cashier calls it out, a customer reads it off their slip and says it back.
 * `RO-2026-09-00342` is a record id — right for tracing, useless at arm's
 * length — so this gets the tinted badge and that gets the reference line.
 *
 * A refund's own short number is the credit note's; the sale it reverses is
 * already named beside it (`D-143`).
 */
const dailyNumber = computed(() => props.order.daily_number ?? null);

/**
 * The moment this row is about (`D-146`).
 *
 * An open bill is dated by when it opened — that is what the cashier is waiting
 * on. A closed one, and a refund, are dated by when they happened; showing the
 * opening time under a tab called "today" is how a bill paid at one in the
 * morning reads as yesterday's.
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

/** The dot beside the status word — colour repeating what the word already says. */
const STATUS_DOT: Record<OpenOrder["status"], string> = {
  draft: "bg-order-draft",
  active: "bg-order-active",
  in_kitchen: "bg-order-in_kitchen",
  pending_payment: "bg-order-pending_payment",
  closed: "bg-order-closed",
  cancelled: "bg-order-cancelled",
  queued: "bg-status-cleaning",
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
    class="relative flex min-h-[76px] items-center gap-6 rounded-rpos-lg border border-line bg-surface px-5 py-[18px] transition-[background-color,border-color] duration-100 ease-rpos hover:border-primary/40"
  >
    <!-- The whole row opens the order; the menu sits above it. -->
    <button
      type="button"
      class="absolute inset-0 rounded-rpos-lg"
      :aria-label="t('card.openOrder')"
      @click="emit('open')"
    />

    <div class="min-w-[92px] shrink-0">
      <!-- A refund row carries its own figure, already negative (`D-143`);
           a sale carries the sale's. -->
      <p
        class="rpos-numeric text-[25px] font-medium leading-none tracking-[-0.8px]"
        :class="order.is_return ? 'text-danger' : 'text-content'"
      >
        {{ formatNumber(order.total_amount, 2) }}
      </p>
      <!-- FR-9, D-070 — a bill money went back out of says so where the money
           is read. Without it a refunded sale looked exactly like a kept one.
           On a refund row the figure above already is the refund. -->
      <!-- **Both of these are values, so neither takes a caption's size**
           (`D-159`). "مرتجع" is an Arabic word saying what the row *is*, so it
           holds 14px; the figure beside it is mono digits and rides at `meta`,
           where 12px stays legible in a way a word would not. -->
      <p
        v-if="order.is_return"
        class="mt-1 text-xs text-danger"
      >
        {{ t("ret.rowLabel") }}
      </p>
      <p
        v-else-if="order.returned_amount"
        class="rpos-numeric mt-1 text-meta text-danger"
      >
        −{{ formatNumber(order.returned_amount, 2) }}
      </p>
      <p
        v-else
        class="mt-1 text-label text-muted"
      >
        {{ t("card.amount") }}
      </p>
    </div>

    <!-- FR-2.10 — the number a cashier calls out. Tinted rather than merely
         bigger: it is the one figure on the row read from across a counter. -->
    <div
      v-if="dailyNumber"
      class="shrink-0 text-center"
    >
      <span
        class="rpos-numeric mx-auto grid h-11 w-11 place-items-center rounded-[13px] bg-primary/10 text-[19px] font-medium text-primary"
      >{{ formatNumber(dailyNumber) }}</span>
      <p class="mt-1 text-label text-muted">
        {{ t("card.dailyNumber") }}
      </p>
    </div>

    <div class="shrink-0 text-center">
      <span
        class="rpos-numeric mx-auto grid h-[38px] w-[38px] place-items-center rounded-xl bg-background text-[15px] text-content"
      >{{ formatNumber(order.item_count) }}</span>
      <p class="mt-1 text-label text-muted">
        {{ t("card.itemCount") }}
      </p>
    </div>

    <!-- `shrink-0`, and no `truncate`: a half-read order number is no use to
         anybody, so this column takes what it needs (`D-060`). The date under
         it is reference, and rides at `meta` — mono digits, where 12px stays
         legible in a way an Arabic word would not. -->
    <div class="hidden min-w-0 flex-1 shrink-0 md:block">
      <p class="rpos-numeric whitespace-nowrap text-[15px] tracking-[0.2px] text-content">
        {{ documentNumber }}
      </p>
      <p class="rpos-numeric mt-0.5 whitespace-nowrap text-meta text-muted">
        {{ dateOnly(happenedAt) }} · {{ timeOnly(happenedAt) }}
      </p>
    </div>

    <!-- Type and status ride together: both answer "what kind of thing is this
         row", and splitting them into two labelled columns was two captions for
         one idea. -->
    <div class="hidden shrink-0 items-center gap-3 sm:flex">
      <span
        class="max-w-[160px] truncate rounded-full border border-line bg-background px-3.5 py-[7px] text-xs text-subtle"
      >
        {{ whereLabel(order) }}
      </span>

      <!-- A draft says so, like every other status.

           It used to be left blank, on the reasoning that every bill on this
           screen is a draft until it moves. That held while the screen showed
           one kind of bill. It does not on a mixed list: one row reads "active"
           and the row under it reads nothing, and a blank in a column every
           other row fills is read as missing data rather than as a state. The
           user asked what the difference between the two tabs was, and the
           answer was on the screen the whole time — invisible. -->
      <span
        class="flex shrink-0 items-center gap-2 text-xs"
        :class="STATUS_TEXT[order.status]"
      >
        <span
          class="h-[7px] w-[7px] shrink-0 rounded-full"
          :class="STATUS_DOT[order.status]"
          aria-hidden="true"
        />
        {{ t(`status.${order.status}`) }}
      </span>
    </div>

    <!-- The avatar circle went here (`D-060`). It was `aria-hidden` decoration
         beside the name it decorated, and it cost fifty pixels the order number
         needed. -->
    <div class="hidden min-w-[108px] shrink-0 lg:block">
      <p class="truncate text-xs font-medium text-content">
        {{ order.cashier_name }}
      </p>
      <p class="mt-0.5 truncate text-label text-muted">
        {{ t("card.cashier") }}
      </p>
    </div>

    <button
      type="button"
      class="relative z-10 grid h-11 w-11 shrink-0 place-items-center rounded-xl text-muted transition-colors duration-100 ease-rpos hover:bg-background"
      :aria-label="t('card.options')"
      :aria-expanded="menuOpen"
      @click.stop="menuOpen = !menuOpen"
    >
      <AppIcon
        name="more"
        :size="20"
      />
    </button>

    <div
      v-if="menuOpen"
      class="absolute top-full end-0 z-20 mt-1 w-56 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
    >
      <button
        type="button"
        class="block min-h-tap w-full px-4 py-3 text-start text-xs transition-colors duration-100 ease-rpos hover:bg-background"
        @click.stop="choose('order')"
      >
        {{ t("card.openOrder") }}
      </button>
      <button
        v-if="props.order.table_number"
        type="button"
        class="block min-h-tap w-full px-4 py-3 text-start text-xs transition-colors duration-100 ease-rpos hover:bg-background"
        @click.stop="choose('floor')"
      >
        {{ t("card.goToTable") }}
      </button>
      <!-- FR-7.5 — the receipt the customer holds, again. A refund's own
           credit note when this row is one (`D-143`). -->
      <button
        v-if="receipt && mayReprint"
        type="button"
        class="block min-h-tap w-full px-4 py-3 text-start text-xs transition-colors duration-100 ease-rpos hover:bg-background"
        @click.stop="choose('reprint')"
      >
        {{ t("print.receiptAgain") }}
      </button>
    </div>
  </div>
</template>
