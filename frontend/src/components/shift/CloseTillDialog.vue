<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CashierTakings from "@/components/shift/CashierTakings.vue";
import TillCount, { type CountRow } from "@/components/shift/TillCount.vue";
import { formatNumber, methodName, t } from "@/i18n";
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
/*
 * **A blind count** (`D-360`). The drawer used to open with what it should hold
 * already typed in, so a cashier could close it without counting a coin — the
 * simulated shift did exactly that. Now the figures that would give the answer
 * away (what should be there, what was sold) stay hidden until the cashier says
 * they have counted; then the difference shows and, if there is one, asks why.
 * Counting again hides them again. Toast and Square offer this as a setting;
 * here it is simply how a drawer is counted, because the other way is not one.
 */
const props = defineProps<{ open: boolean; settlementRequired: boolean }>();
const emit = defineEmits<{ close: [] }>();

const shift = useShiftStore();

const report = ref<ShiftReport | null>(null);
const counted = ref<Record<string, string>>({});
const reason = ref("");
/** Whether the cashier has said the count is done, and may now see the comparison. */
const revealed = ref(false);

watch(
  () => props.open,
  async (isOpen) => {
    report.value = null;
    counted.value = {};
    reason.value = "";
    revealed.value = !props.settlementRequired;
    if (!isOpen) return;

    // `true`: the cashier is about to count, so the drawer opens (`D-093`).
    report.value = await shift.tillSummary(true);
    if (!report.value) return;

    // A terminal that does not reconcile (BR-042) is shown, not counted: its
    // figures are the expected ones. One that does starts empty.
    if (!props.settlementRequired) {
      counted.value = Object.fromEntries(
        report.value.by_method
          .filter((row) => row.kind === "till")
          .map((row) => [row.method, String(row.expected)]),
      );
    }
  },
);

function countDone(): void {
  revealed.value = true;
}

/** Count again: the comparison hides again, so the second count is as blind as the first. */
function recount(): void {
  counted.value = {};
  reason.value = "";
  revealed.value = false;
}

function onCount(method: string, value: string): void {
  counted.value[method] = value;
}

const tillRows = computed(() => report.value?.by_method.filter((row) => row.kind === "till") ?? []);

/** What `TillCount` needs: a method and the figure it is measured against. */
const countRows = computed<CountRow[]>(() =>
  tillRows.value.map((row) => ({ method: row.method, expected: revealed.value ? row.expected : null })),
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
const needsReason = computed(() => revealed.value && Math.abs(totalVariance.value) >= 0.005);

async function confirm(): Promise<void> {
  if (!revealed.value || (needsReason.value && !reason.value.trim())) return;

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
    pad
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
      <p
        v-if="!revealed"
        data-blind
        class="mb-3 text-center text-xs text-subtle"
      >
        {{ t("shift.countBlind") }}
      </p>

      <!-- What was sold through this drawer — after the count, not before it (`D-360`). -->
      <dl
        v-if="revealed"
        class="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded bg-surface p-3 text-sm"
      >
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

      <CashierTakings
        v-if="revealed"
        :rows="report.by_cashier"
      />

      <TillCount
        class="mb-4"
        :rows="countRows"
        :values="counted"
        :readonly="!settlementRequired || revealed"
        @update="onCount"
      />

      <!--
        D-029 — reported, never reconciled. The platform has the money; the
        drawer never did, and counting it would make every close look short.
      -->
      <div
        v-if="creditRows.length"
        class="mb-4 rounded bg-surface p-3"
      >
        <p class="mb-2 text-xs font-semibold text-muted">
          {{ t("shift.creditNote") }}
        </p>
        <div
          v-for="row in creditRows"
          :key="row.method"
          class="flex items-center justify-between gap-3 text-sm text-muted"
        >
          <span class="min-w-0 truncate">{{ methodName(row.method) }}</span>
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
          class="min-h-tap w-full rounded border border-line bg-surface px-3"
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

      <!-- One button to count, as on Foodics: the backdrop closes without
           keeping anything (`D-370`). After the count the till shows what it
           expected, and the choice is real — close on that, or count again. -->
      <button
        v-if="!revealed"
        type="button"
        class="rpos-pad-done"
        @click="countDone"
      >
        {{ t("action.done") }}
      </button>
      <div
        v-else
        class="flex flex-col gap-2"
      >
        <button
          type="button"
          class="rpos-pad-done"
          :disabled="shift.busy || (needsReason && !reason.trim())"
          @click="confirm"
        >
          {{ t("shift.closeTill") }}
        </button>
        <button
          v-if="settlementRequired"
          type="button"
          class="min-h-tap text-subtle"
          @click="recount"
        >
          {{ t("shift.recount") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
