<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useShiftStore } from "@/stores/shift";

/**
 * End of day — the branch's report, and the decision to close on it (FR-8.2, 8.3).
 *
 * Shown before anything is committed, because closing the day is what the books
 * are written from and a cashier should see the figure they are signing off.
 *
 * **An order still open blocks it**, unless a manager says otherwise: closing
 * across one strands a bill in a report that says the day is finished. And any
 * drawer left open is swept up at its expected figures — the cashier who went
 * home is not coming back to count it.
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const shift = useShiftStore();

const report = ref<ShiftReport | null>(null);
const force = ref(false);

watch(
  () => props.open,
  async (isOpen) => {
    report.value = null;
    force.value = false;
    if (isOpen) report.value = await shift.daySummary();
  },
);

const stillOpen = computed(() => report.value?.orders.still_open ?? 0);

async function confirm(): Promise<void> {
  const done = await shift.closeDay(force.value);
  if (done) emit("close");
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shift.closeDayTitle')"
    :dismissible="true"
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
          {{ t("totals.discount") }}
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
        <dt class="text-muted">
          {{ t("shift.tillExpected") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ money(report.till_expected) }}
        </dd>
        <dt
          v-if="report.credit_total"
          class="text-muted"
        >
          {{ t("shift.creditTotal") }}
        </dt>
        <dd
          v-if="report.credit_total"
          class="rpos-numeric text-end"
        >
          {{ money(report.credit_total) }}
        </dd>
      </dl>

      <!-- FR-8.3 — how the day split, which is the first thing a manager looks at. -->
      <div
        v-if="report.by_order_type.length"
        class="mb-4 space-y-1"
      >
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

      <label
        v-if="stillOpen"
        class="mb-4 flex items-start gap-3 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
      >
        <input
          v-model="force"
          type="checkbox"
          class="mt-0.5 h-5 w-5 shrink-0"
        >
        <span>{{ t("shift.stillOpen", { count: formatNumber(stillOpen) }) }}</span>
      </label>

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
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="shift.busy || (Boolean(stillOpen) && !force)"
          @click="confirm"
        >
          {{ t("shift.closeDay") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
