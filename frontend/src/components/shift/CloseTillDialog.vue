<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import AmountKeypad from "@/components/shift/AmountKeypad.vue";
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

    report.value = await shift.tillSummary();
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

/** Which method is being counted, if any — the keypad's subject (D-049). */
const typing = ref<string | null>(null);

function onKeypad(value: string): void {
  if (typing.value) counted.value[typing.value] = value;
  typing.value = null;
}

const tillRows = computed(() => report.value?.by_method.filter((row) => row.kind === "till") ?? []);
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
    :title="typing ? t('keypad.title', { method: typing }) : t('shift.closeTillTitle')"
    :dismissible="true"
    @close="emit('close')"
  >
    <!-- The keypad takes the dialog over while a figure is being counted. -->
    <AmountKeypad
      v-if="typing"
      :value="counted[typing] || '0'"
      @close="typing = null"
      @confirm="onKeypad"
    />

    <p
      v-else-if="!report"
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

      <div class="mb-4 space-y-2">
        <div
          v-for="row in tillRows"
          :key="row.method"
        >
          <div class="flex items-center gap-3">
            <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ row.method }}</span>
            <span class="rpos-numeric w-24 text-end text-sm text-muted">{{
              money(row.expected)
            }}</span>
            <button
              type="button"
              class="rpos-numeric min-h-tap w-28 rounded-rpos border border-line bg-background px-3 text-end text-lg font-semibold transition duration-200 ease-rpos enabled:hover:border-primary disabled:opacity-50"
              :disabled="!settlementRequired"
              @click="typing = row.method"
            >
              {{ money(Number(counted[row.method]) || 0) }}
            </button>
          </div>
          <p
            v-if="settlementRequired && Math.abs(varianceOf(row.method, row.expected)) >= 0.005"
            class="rpos-numeric mt-1 text-end text-xs"
            :class="varianceOf(row.method, row.expected) < 0 ? 'text-danger' : 'text-status-available'"
          >
            {{ money(varianceOf(row.method, row.expected)) }}
          </p>
        </div>
      </div>

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
