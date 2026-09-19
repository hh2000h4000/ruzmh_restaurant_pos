<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CashierTakings from "@/components/shift/CashierTakings.vue";
import TillCount, { type CountRow } from "@/components/shift/TillCount.vue";
import { formatNumber, t } from "@/i18n";
import { useShiftStore } from "@/stores/shift";

/**
 * Handing the drawer back, and accounting for it (FR-8.2, BR-042, BR-043).
 *
 * **Credit is shown and never counted** (D-029). A delivery platform already
 * took the customer's money — nothing of it is in this drawer. Counting it into
 * the expected cash would show a shortfall the size of the day's app orders,
 * every day, and a variance that is always wrong by a known amount hides a real
 * one. So those rows are listed, greyed, with no box to type in.
 *
 * The variance shown here is arithmetic on figures the server gave, so the
 * cashier sees the consequence before confirming — the server computes it again
 * and is the one that decides (`CLAUDE.md` §5.1).
 *
 * **Counting is `TillCount`'s job, shared with opening** (D-052). It used to
 * hide the keypad behind a tap on each figure and then take the whole dialog
 * over, while opening a shift showed the keypad straight away — the same
 * question in two shapes, so a cashier who learned one screen did not know the
 * other.
 */
const props = defineProps<{ open: boolean; settlementRequired: boolean }>();
const emit = defineEmits<{ close: [] }>();

const shift = useShiftStore();

const report = ref<ShiftReport | null>(null);
const counted = ref<Record<string, string>>({});
const reason = ref("");

watch(
  () => props.open,
  async (isOpen) => {
    report.value = null;
    counted.value = {};
    reason.value = "";
    if (!isOpen) return;

    // `true`: the cashier is about to count, so the drawer opens (`D-093`).
    report.value = await shift.tillSummary(true);
    if (!report.value) return;

    // Pre-filled with what is expected: a drawer that balances needs no typing,
    // and the cashier corrects only what differs.
    counted.value = Object.fromEntries(
      report.value.by_method
        .filter((row) => row.kind === "till")
        .map((row) => [row.method, String(row.expected)]),
    );
  },
);

function onCount(method: string, value: string): void {
  counted.value[method] = value;
}

const tillRows = computed(() => report.value?.by_method.filter((row) => row.kind === "till") ?? []);

/** What `TillCount` needs: a method and the figure it is measured against. */
const countRows = computed<CountRow[]>(() =>
  tillRows.value.map((row) => ({ method: row.method, expected: row.expected })),
);
const creditRows = computed(
  () => report.value?.by_method.filter((row) => row.kind === "credit") ?? [],
);

function varianceOf(method: string, expected: number): number {
  if (!props.settlementRequired) return 0;
  return (Number(counted.value[method]) || 0) - expected;
}

const totalVariance = computed(() =>
  tillRows.value.reduce((sum, row) => sum + varianceOf(row.method, row.expected), 0),
);

/** BR-043 — a difference has to be answered for before the drawer closes. */
const needsReason = computed(() => Math.abs(totalVariance.value) >= 0.005);

async function confirm(): Promise<void> {
  if (needsReason.value && !reason.value.trim()) return;

  const amounts: Record<string, number> = {};
  for (const [method, value] of Object.entries(counted.value)) {
    amounts[method] = Number(value) || 0;
  }

  const done = await shift.closeTill(
    props.settlementRequired ? amounts : undefined,
    reason.value.trim() || null,
  );
  if (done) emit("close");
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shift.closeTillTitle')"
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
      <!-- What was sold through this drawer, before anything is counted. -->
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
      </dl>

      <CashierTakings :rows="report.by_cashier" />

      <TillCount
        class="mb-4"
        :rows="countRows"
        :values="counted"
        :readonly="!settlementRequired"
        @update="onCount"
      />

      <!--
        D-029 — reported, never reconciled. The platform has the money; the
        drawer never did, and counting it would make every close look short.
      -->
      <div
        v-if="creditRows.length"
        class="mb-4 rounded-rpos bg-background p-3"
      >
        <p class="mb-2 text-xs font-semibold text-muted">
          {{ t("shift.creditNote") }}
        </p>
        <div
          v-for="row in creditRows"
          :key="row.method"
          class="flex items-center justify-between gap-3 text-sm text-muted"
        >
          <span class="min-w-0 truncate">{{ row.method }}</span>
          <span class="rpos-numeric">{{ money(row.sales) }}</span>
        </div>
      </div>

      <div
        v-if="settlementRequired && needsReason"
        class="mb-4"
      >
        <p class="mb-1.5 flex items-center justify-between text-sm font-semibold">
          <span>{{ t("shift.variance") }}</span>
          <span
            class="rpos-numeric"
            :class="totalVariance < 0 ? 'text-danger' : 'text-status-available'"
          >{{ money(totalVariance) }}</span>
        </p>
        <input
          v-model="reason"
          type="text"
          class="min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          :placeholder="t('shift.varianceReason')"
        >
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
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="shift.busy || (needsReason && !reason.trim())"
          @click="confirm"
        >
          {{ t("shift.closeTill") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
