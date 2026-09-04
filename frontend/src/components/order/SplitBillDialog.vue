<script setup lang="ts">
/**
 * Take some of a bill onto a bill of its own (`FR-2.12`, `BR-067`).
 *
 * Two columns, and a tap moves a line across — the arrangement Toast, Micros
 * and Lightspeed all settled on, for the plain reason that the guests are
 * standing there and the cashier has to see both bills as they build them.
 *
 * **A tap moves one unit, not the whole line.** "2 x cola" between two people
 * is the ordinary case, and it should cost one tap each rather than a dialog
 * asking how many. Tapping the line on the right sends a unit back.
 *
 * **Nothing happens until Confirm.** The moves are arranged locally and sent as
 * one call, so a cashier can change their mind without a trail of half-finished
 * bills — which is what Fitec's Confirm/Cancel does, and it is right.
 *
 * The running totals come from the server (`CLAUDE.md` §5.1): a figure read out
 * to a customer has to be the figure the invoice will carry.
 */
import { computed, ref, watch } from "vue";

import * as orderApi from "@/api/order";
import type { MovedLine, OrderDetail } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import BillCard, { type BillCardLine } from "@/components/order/BillCard.vue";
import { t } from "@/i18n";

const props = defineProps<{ open: boolean; order: OrderDetail | null }>();
const emit = defineEmits<{ done: [target: string]; close: [] }>();

/** How much of each line has been moved across, by line `idx`. */
const moved = ref<Map<number, number>>(new Map());
const preview = ref<orderApi.SplitPreview | null>(null);
const busy = ref(false);
const failure = ref<string | null>(null);

/** A voided line is not on the bill any more and cannot be moved (`BR-067`). */
const movable = computed(() => (props.order?.items ?? []).filter((line) => line.status !== "void"));

const rows = computed<MovedLine[]>(() =>
  [...moved.value.entries()]
    .filter(([, qty]) => qty > 0)
    .map(([idx, qty]) => ({ idx, qty })),
);

/**
 * A line's own figure, but **only while the whole line sits on one side**.
 *
 * Half a line's amount is a number the server has not given us, and dividing
 * one here is exactly the computation `CLAUDE.md` §5.1 forbids — the till
 * displays money and does not work it out. A split line therefore shows its
 * quantity and a dash, and the authoritative figure is the column total, which
 * the server prices.
 */
function share(line: { amount: number; qty: number }, part: number): number | null {
  return part === line.qty ? line.amount : null;
}

const staying = computed<BillCardLine[]>(() =>
  movable.value
    .map((line) => ({ line, left: line.qty - (moved.value.get(line.idx) ?? 0) }))
    .filter(({ left }) => left > 0)
    .map(({ line, left }) => ({
      key: line.idx,
      name: line.item_name,
      qty: left,
      amount: share(line, left),
      sent: line.status === "sent",
    })),
);

const going = computed<BillCardLine[]>(() =>
  movable.value
    .map((line) => ({ line, gone: moved.value.get(line.idx) ?? 0 }))
    .filter(({ gone }) => gone > 0)
    .map(({ line, gone }) => ({
      key: line.idx,
      name: line.item_name,
      qty: gone,
      amount: share(line, gone),
      sent: line.status === "sent",
    })),
);

function take(idx: number): void {
  const line = movable.value.find((row) => row.idx === idx);
  if (!line) return;

  const gone = moved.value.get(idx) ?? 0;
  if (gone >= line.qty) return;

  moved.value = new Map(moved.value).set(idx, gone + 1);
}

function giveBack(idx: number): void {
  const gone = moved.value.get(idx) ?? 0;
  if (gone <= 0) return;

  const next = new Map(moved.value);
  next.set(idx, gone - 1);
  moved.value = next;
}

/** Reset every time it opens: a half-arranged split from last time is a trap. */
watch(
  () => props.open,
  (open) => {
    moved.value = new Map();
    preview.value = null;
    failure.value = null;
    if (!open) return;
  },
);

watch(rows, async (current) => {
  if (!props.order || !current.length) {
    preview.value = null;
    return;
  }

  try {
    preview.value = await orderApi.previewSplit(props.order.order_name, current);
  } catch (cause) {
    // The preview is a courtesy; Confirm asks the server again and is the one
    // that must not fail quietly.
    preview.value = null;
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
});

async function confirm(): Promise<void> {
  if (!props.order || !rows.value.length || busy.value) return;

  busy.value = true;
  failure.value = null;
  try {
    const outcome = await orderApi.splitBill({
      order_name: props.order.order_name,
      rows: rows.value,
    });
    emit("done", outcome.target);
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('split.title')"
    wide
    @close="emit('close')"
  >
    <p
      v-if="failure"
      class="mb-3 rounded-rpos bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <div class="grid grid-cols-2 gap-3 h-[55vh]">
      <BillCard
        :title="`#${order?.daily_number ?? ''}`"
        :subtitle="t('split.original')"
        :lines="staying"
        :total="preview ? preview.source.total_amount : (rows.length ? null : order?.total_amount ?? null)"
        :tax="preview ? preview.source.tax_amount : null"
        :empty="t('split.allMoved')"
        interactive
        @pick="take"
      />
      <BillCard
        :title="t('split.newBill')"
        :subtitle="t('split.tapToReturn')"
        :lines="going"
        :total="preview ? preview.target.total_amount : null"
        :tax="preview ? preview.target.tax_amount : null"
        :empty="t('split.tapToMove')"
        interactive
        @pick="giveBack"
      />
    </div>

    <div class="mt-4 flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.cancel") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
        :disabled="!rows.length || busy"
        @click="confirm"
      >
        {{ t("split.confirm") }}
      </button>
    </div>
  </BaseDialog>
</template>
