<script setup lang="ts">
import type { ShiftReport } from "@/api/shift";
import { formatNumber, t } from "@/i18n";

/**
 * What each person took and gave back (FR-8.3, `D-218`).
 *
 * **One list for the drawer and the day**, because it is one question: who rang
 * this money. A shared drawer is counted once for everybody on it — which is
 * what makes a difference hard to pin on anyone — so this is where it is still
 * traced to a name, as Vitec's shift report does.
 *
 * **Drawn only when more than one person is on it.** A personal drawer holds its
 * own cashier, and a single line repeating whose drawer it is says nothing the
 * dialog does not already say.
 */
defineProps<{ rows: ShiftReport["by_cashier"] }>();

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <div
    v-if="rows.length > 1"
    class="mb-4 rounded-rpos bg-background p-3"
  >
    <p class="mb-2 text-xs font-semibold text-muted">
      {{ t("shift.byCashier") }}
    </p>
    <div
      v-for="row in rows"
      :key="row.user"
      class="flex items-center justify-between gap-3 text-sm"
    >
      <span class="min-w-0 truncate">{{ row.name }}</span>
      <span class="rpos-numeric shrink-0 text-muted">
        {{ formatNumber(row.count) }} · {{ money(row.sales) }}
        <template v-if="row.returns">
          · {{ t("shift.cashierReturns", { amount: money(row.returns) }) }}
        </template>
      </span>
    </div>
  </div>
</template>
