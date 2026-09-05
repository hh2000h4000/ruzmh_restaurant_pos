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
 * **Credit methods are not offered.** A platform never puts anything in a till,
 * so a float against one would inflate an expected figure for cash that does
 * not exist (D-029). The server refuses them too; keeping them off the screen
 * saves the cashier wondering why.
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const session = useSessionStore();
const shift = useShiftStore();

/**
 * The terminal's own methods.
 *
 * The `is_credit` flag lives on the Mode of Payment, which this payload does not
 * carry — so the server does the filtering and this list is a convenience, not
 * the rule.
 */
const methods = computed(() =>
  (session.data?.payment_methods ?? []).map((row) => row.mode_of_payment),
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
    @close="emit('close')"
  >
    <p class="mb-3 text-sm text-muted">
      {{ t("shift.openTillBody") }}
    </p>

    <TillCount
      class="mb-4"
      :rows="rows"
      :values="floats"
      @update="onCount"
    />

    <p
      v-if="methods.length > 1 && total"
      class="mb-4 flex items-center justify-between rounded-rpos bg-background p-3 text-sm"
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
        class="min-h-tap flex-1 rounded-rpos bg-primary font-bold text-primary-contrast disabled:opacity-40"
        :disabled="shift.busy"
        @click="confirm"
      >
        {{ t("shift.openTill") }}
      </button>
    </div>
  </BaseDialog>
</template>
