<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import { formatNumber, methodName, t } from "@/i18n";

/**
 * Counting money into the till, and counting it back out (D-049, D-052).
 *
 * **One component, because it is one question.** Opening a shift and closing it
 * both ask "how much of each method is in the drawer" — and they had answered it
 * two different ways: opening showed the keypad straight away, closing hid it
 * behind a tap on a figure and then took the whole dialog over. A cashier who
 * learned one screen did not know the other, and a fix to either was a fix to
 * only half the app.
 *
 * The one real difference is that closing has a figure to compare against, so
 * that is a column here rather than a second screen: pass `expected` and the row
 * shows what was owed and what the count differs by.
 *
 * **The keypad is always on screen.** A till is a touch device that raises no
 * soft keyboard, so a figure behind a tap is a figure that looks untypable.
 */
export interface CountRow {
  method: string;
  /** What the server says should be there. Omit when nothing is owed yet. */
  expected?: number | null;
}

const props = defineProps<{
  rows: CountRow[];
  /** method → what has been typed, as typed. The owner holds it. */
  values: Record<string, string>;
  /** Shown but not typable — a terminal that does not reconcile (BR-042). */
  readonly?: boolean;
}>();

const emit = defineEmits<{ update: [method: string, value: string] }>();

/** Which row the keypad is editing. */
const active = ref("");

watch(
  () => props.rows,
  (rows) => {
    if (!rows.some((row) => row.method === active.value)) active.value = rows[0]?.method ?? "";
  },
  { immediate: true, deep: true },
);

/**
 * One method and nothing owed is not a choice — it is a float, and a list of
 * one row above a keypad is a row that says nothing the keypad does not.
 */
const listed = computed(
  () => props.rows.length > 1 || props.rows.some((row) => row.expected !== null && row.expected !== undefined),
);

function typed(method: string): number {
  return Number(props.values[method]) || 0;
}

function variance(row: CountRow): number | null {
  if (row.expected === null || row.expected === undefined) return null;
  return typed(row.method) - row.expected;
}

/** Below half a halala is the same figure; anything else is a real difference. */
function differs(row: CountRow): boolean {
  const value = variance(row);
  return value !== null && Math.abs(value) >= 0.005;
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <div>
    <!-- The list scrolls and the keypad stays put (`D-329`): ten methods at a
         close must not push the keys a cashier types on off the screen. -->
    <div
      v-if="listed"
      data-methods
      class="mb-3 max-h-[13.5rem] space-y-1.5 overflow-y-auto"
    >
      <button
        v-for="row in rows"
        :key="row.method"
        type="button"
        class="flex w-full items-center gap-3 rounded-rpos border px-3 py-2 text-start transition duration-200 ease-rpos disabled:opacity-60"
        :class="
          active === row.method && !readonly
            ? 'border-primary bg-primary/5'
            : 'border-line bg-background'
        "
        :disabled="readonly"
        :aria-pressed="active === row.method"
        @click="active = row.method"
      >
        <span class="min-w-0 flex-1">
          <span class="block truncate text-sm font-semibold">{{ methodName(row.method) }}</span>
          <span
            v-if="row.expected !== null && row.expected !== undefined"
            class="rpos-numeric block truncate text-xs text-muted"
          >{{ t("shift.expected") }} {{ money(row.expected) }}</span>
        </span>

        <span class="shrink-0 text-end">
          <span class="rpos-numeric block text-lg font-bold">{{ money(typed(row.method)) }}</span>
          <span
            v-if="differs(row)"
            class="rpos-numeric block text-xs"
            :class="variance(row)! < 0 ? 'text-danger' : 'text-status-available'"
          >{{ money(variance(row)!) }}</span>
        </span>
      </button>
    </div>

    <AmountKeypad
      v-if="active && !readonly"
      :label="listed ? undefined : methodName(active)"
      :value="values[active] ?? '0'"
      @update="emit('update', active, $event)"
    />
  </div>
</template>
