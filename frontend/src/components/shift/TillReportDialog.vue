<script setup lang="ts">
import { ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CashierTakings from "@/components/shift/CashierTakings.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useNoticeStore } from "@/stores/notice";
import { useShiftStore } from "@/stores/shift";

/**
 * The X report on the screen, with paper as a choice rather than the only way
 * to read it (`D-237`).
 *
 * The figures were printable and nothing else: checking what the drawer should
 * hold meant a receipt, and the user's customers print it twice around every
 * break to compare. Reading it costs no paper, works while the printer is
 * jammed, and is what every till of this kind offers — Loyverse shows the shift
 * report on screen and keeps printing a separate tap.
 *
 * **It does not open the cash drawer.** The closing screen does, because
 * somebody is standing there to count (`D-093`); a cashier glancing at the
 * figures mid-shift, or a manager over their shoulder, must not pop it in front
 * of a queue (`D-237`).
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const shift = useShiftStore();
const notice = useNoticeStore();

const report = ref<ShiftReport | null>(null);
const printing = ref(false);

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      report.value = null;
      return;
    }
    report.value = await shift.tillSummary();
  },
  { immediate: true },
);

async function print(): Promise<void> {
  if (printing.value) return;

  printing.value = true;
  try {
    if (await shift.printTillReport()) notice.info(t("print.reportSent"));
  } finally {
    printing.value = false;
  }
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shift.reportTitle')"
    @close="emit('close')"
  >
    <p
      v-if="!report"
      class="flex items-center gap-2 text-sm text-muted"
    >
      <AppIcon
        name="refresh"
        class="animate-spin"
        :size="18"
      />
      {{ t("common.loading") }}
    </p>

    <template v-else>
      <dl class="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded-rpos bg-background p-3 text-sm">
        <dt class="text-muted">
          {{ t("shift.ordersClosed") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ formatNumber(report.orders.closed) }}
        </dd>
        <dt class="text-muted">
          {{ t("shift.sales") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ money(report.sales) }}
        </dd>
        <dt class="text-muted">
          {{ t("shift.discounts") }}
        </dt>
        <dd class="rpos-numeric text-end">
          {{ money(report.discounts) }}
        </dd>
        <dt class="text-muted">
          {{ t("shift.voids") }}
        </dt>
        <dd class="rpos-numeric text-end">
          {{ formatNumber(report.voids) }}
        </dd>
        <dt class="font-semibold">
          {{ t("shift.expected") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ money(report.till_expected) }}
        </dd>
      </dl>

      <!-- Every method, and what each took — the line a manager compares the
           card terminal's own total against. -->
      <div class="mb-4 rounded-rpos bg-background p-3">
        <p class="mb-2 text-xs font-semibold text-muted">
          {{ t("shift.byMethod") }}
        </p>
        <div
          v-for="row in report.by_method"
          :key="row.method"
          class="flex items-center justify-between gap-3 text-sm"
          :class="row.kind === 'credit' ? 'text-muted' : ''"
        >
          <span class="min-w-0 truncate">{{ row.method }}</span>
          <span class="rpos-numeric shrink-0">{{ money(row.sales) }}</span>
        </div>
        <p
          v-if="report.credit_total"
          class="mt-2 text-xs text-muted"
        >
          {{ t("shift.creditNote") }}
        </p>
      </div>

      <CashierTakings :rows="report.by_cashier" />

      <!-- What was sold, by the kind of order it was (FR-8.3). -->
      <div
        v-if="report.by_order_type.length"
        class="mb-4 rounded-rpos bg-background p-3"
      >
        <p class="mb-2 text-xs font-semibold text-muted">
          {{ t("shift.byOrderType") }}
        </p>
        <div
          v-for="row in report.by_order_type"
          :key="row.order_type"
          class="flex items-center justify-between gap-3 text-sm"
        >
          <span class="min-w-0 truncate">{{ pick(row.title_ar, row.order_type) }}</span>
          <span class="rpos-numeric shrink-0 text-muted">
            {{ formatNumber(row.count) }} · {{ money(row.sales) }}
          </span>
        </div>
      </div>

      <p
        v-if="shift.error"
        role="alert"
        class="mb-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ shift.error }}
      </p>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="emit('close')"
        >
          {{ t("action.back") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-semibold text-on-primary disabled:opacity-60"
          :disabled="printing"
          @click="print"
        >
          {{ printing ? t("common.loading") : t("shift.printReport") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
