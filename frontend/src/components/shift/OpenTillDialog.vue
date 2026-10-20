<script setup lang="ts">
import { computed, ref, watch } from "vue";

import BaseDialog from "@/components/BaseDialog.vue";
import TillCount, { type CountRow } from "@/components/shift/TillCount.vue";
import { formatNumber, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";

/**
 * Opening a shift, and saying what is in the till (FR-8.1 step 3).
 *
 * **One screen.** It was two — a row reading "Cash 0.00", then a keypad behind
 * a tap on it. For a shop with a single cash float that is the same figure
 * asked for twice. The keypad *is* the dialog now, and `TillCount` puts the
 * methods above it only when there is more than one to choose between.
 *
 * Counting is `TillCount`'s job, shared with closing (D-052): the two screens
 * ask the same question and must not answer it in two shapes.
 *
 * The float is what the close is measured against: money in the till before a
 * riyal was taken. Zero is a fine answer — the till is then expected to hold
 * only what was sold.
 *
 * **Only cash is asked for** (`D-329`). A platform, a card machine and a gift
 * card never put anything in a till before the first sale, so a float against
 * one would inflate an expected figure for money that does not exist (D-029).
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const session = useSessionStore();
const shift = useShiftStore();

/**
 * The methods that hold notes and coins — the only ones a float can be in.
 *
 * **It listed every method on the terminal**, and the owner's screenshot showed
 * where that goes: a float box for a gift card and one for HungerStation, and a
 * dialog one row taller for every method added — "imagine I have ten". A card
 * machine, a gift card and a delivery platform start a shift holding nothing.
 * Foodics, Square and Toast all ask one thing when a drawer opens: the cash in
 * it. So a restaurant with one cash method sees the keypad and no list at all.
 */
const methods = computed(() =>
  (session.data?.payment_methods ?? []).filter((row) => row.is_cash).map((row) => row.mode_of_payment),
);

/** Nothing is owed at the start of a shift, so no row carries an expected. */
const rows = computed<CountRow[]>(() => methods.value.map((method) => ({ method })));

const floats = ref<Record<string, string>>({});

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    floats.value = Object.fromEntries(methods.value.map((method) => [method, "0"]));
  },
);

const total = computed(() =>
  Object.values(floats.value).reduce((sum, value) => sum + (Number(value) || 0), 0),
);

function onCount(method: string, value: string): void {
  floats.value[method] = value;
}

async function confirm(): Promise<void> {
  const opening: Record<string, number> = {};
  for (const [method, value] of Object.entries(floats.value)) {
    const amount = Number(value) || 0;
    if (amount) opening[method] = amount;
  }

  const done = await shift.openTill(opening);
  if (done) emit("close");
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shift.openTillTitle')"
    pad
    @close="emit('close')"
  >
    <!-- A terminal with no cash method has no float to count; it opens on zero. -->
    <TillCount
      v-if="rows.length"
      class="mb-4"
      :rows="rows"
      :values="floats"
      @update="onCount"
    />

    <p
      v-if="methods.length > 1 && total"
      class="mb-4 flex items-center justify-between rounded bg-surface p-3 text-sm"
    >
      <span class="text-muted">{{ t("shift.openingTotal") }}</span>
      <span class="rpos-numeric font-bold">{{ formatNumber(total, 2) }}</span>
    </p>

    <p
      v-if="shift.error"
      role="alert"
      class="mb-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ shift.error }}
    </p>

    <!-- One button: the backdrop is the way out, and only this opens the till (`D-370`). -->
    <button
      type="button"
      class="rpos-pad-done"
      :disabled="shift.busy"
      @click="confirm"
    >
      {{ t("action.done") }}
    </button>
  </BaseDialog>
</template>
