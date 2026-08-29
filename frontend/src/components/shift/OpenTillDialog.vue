<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import { formatNumber, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";

/**
 * Taking the drawer, and saying what is already in it (FR-8.1 step 3).
 *
 * The float is what the close is measured against: money that was in the drawer
 * before a riyal was taken. Leave it at zero and the count still works — it is
 * simply expected to hold only what was sold.
 *
 * **Credit methods are not offered.** A platform never puts anything in a
 * drawer, so a float against one would inflate an expected figure for cash that
 * does not exist (D-029). The server refuses them too; this keeps the field off
 * the screen so nobody wonders why.
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const session = useSessionStore();
const shift = useShiftStore();

/**
 * The terminal's own methods, minus anything settled on account.
 *
 * `payment_methods` on the session is what this POS Profile accepts; the
 * `is_credit` flag lives on the Mode of Payment, which the payload does not
 * carry — so the server does the filtering and this list is a convenience, not
 * the rule.
 */
const methods = computed(() => session.data?.payment_methods ?? []);

const floats = ref<Record<string, string>>({});

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    floats.value = Object.fromEntries(methods.value.map((row) => [row.mode_of_payment, ""]));
  },
);

/**
 * Which method is being typed, if any.
 *
 * A till is a touch screen and a number field there waits on a keyboard that
 * may never come, so the amount opens a keypad instead (D-049).
 */
const typing = ref<string | null>(null);

function amountOf(method: string): string {
  return floats.value[method] || "0";
}

function onKeypad(value: string): void {
  if (typing.value) floats.value[typing.value] = value === "0" ? "" : value;
  typing.value = null;
}

const total = computed(() =>
  Object.values(floats.value).reduce((sum, value) => sum + (Number(value) || 0), 0),
);

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
    :title="typing ? t('keypad.title', { method: typing }) : t('shift.openTillTitle')"
    :dismissible="true"
    @close="emit('close')"
  >
    <!-- The keypad takes the dialog over while a figure is being typed. -->
    <AmountKeypad
      v-if="typing"
      :value="amountOf(typing)"
      @close="typing = null"
      @confirm="onKeypad"
    />

    <template v-else>
      <p class="mb-4 text-sm text-muted">
        {{ t("shift.openTillBody") }}
      </p>

      <div class="mb-4 space-y-2">
        <div
          v-for="row in methods"
          :key="row.mode_of_payment"
          class="flex items-center gap-3"
        >
          <span class="min-w-0 flex-1 truncate text-sm font-medium">{{ row.mode_of_payment }}</span>
          <button
            type="button"
            class="rpos-numeric min-h-tap w-32 rounded-rpos border border-line bg-background px-3 text-end text-lg font-semibold transition duration-200 ease-rpos hover:border-primary"
            @click="typing = row.mode_of_payment"
          >
            {{ formatNumber(Number(floats[row.mode_of_payment]) || 0, 2) }}
          </button>
        </div>
      </div>

      <p
        v-if="total"
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
          class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="shift.busy"
          @click="confirm"
        >
          <AppIcon
            name="card"
            :size="20"
          />
          {{ t("shift.openTill") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
