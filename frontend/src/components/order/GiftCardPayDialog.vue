<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import { lookupGiftCard } from "@/api/giftCard";
import BaseDialog from "@/components/BaseDialog.vue";
import CodePad from "@/components/order/CodePad.vue";
import { formatNumber, t } from "@/i18n";

/**
 * Which card is paying, and what is on it (`D-256`).
 *
 * **The balance is read before anything is taken.** A card is the one payment
 * method whose limit the cashier cannot see — notes are counted in the hand and
 * a bank card is the bank's problem, but a gift card may hold forty when the
 * bill is eighty. Showing what is left turns a refusal at Confirm into a
 * sentence the cashier says while the guest is still deciding.
 *
 * **It only looks it up.** Nothing is spent here: the amount is taken on the
 * payment screen like every other method, and the server takes it off the card
 * only once the invoice has posted.
 *
 * Same field and same pad as the coupon screen (`D-250`, `D-252`).
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; found: [card: { number: string; balance: number }] }>();

const number = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const found = ref<{ number: string; balance: number } | null>(null);
const field = ref<HTMLInputElement | null>(null);

const canSend = computed(() => number.value.trim().length > 0 && !busy.value);

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;
    number.value = "";
    error.value = null;
    found.value = null;

    // Focused on open, so a wedge scanner's read lands in the field.
    await nextTick();
    field.value?.focus();
  },
);

async function check(): Promise<void> {
  if (!canSend.value) return;

  busy.value = true;
  error.value = null;
  found.value = null;
  try {
    const card = await lookupGiftCard(number.value.trim());
    found.value = { number: card.card_number, balance: card.balance };
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}

function use(): void {
  if (!found.value) return;
  emit("found", found.value);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('giftCard.payTitle')"
    @close="emit('close')"
  >
    <p class="mb-4 text-xs text-subtle">
      {{ t("giftCard.payBody") }}
    </p>

    <input
      ref="field"
      :value="number"
      type="text"
      autocapitalize="characters"
      autocomplete="off"
      dir="ltr"
      class="mb-3 w-full rounded-rpos border border-line bg-background p-3 text-center text-lg tracking-widest"
      :placeholder="t('giftCard.numberPlaceholder')"
      @input="
        number = ($event.target as HTMLInputElement).value.toUpperCase();
        found = null;
      "
      @keyup.enter="check"
    >

    <CodePad
      class="mb-3"
      :value="number"
      @update="
        number = $event;
        found = null;
      "
    />

    <!-- What is on it, before a single riyal is taken off. -->
    <div
      v-if="found"
      class="mb-3 rounded-rpos bg-background p-3 text-center"
    >
      <p class="text-xs text-muted">
        {{ t("giftCard.balance") }}
      </p>
      <p class="rpos-numeric text-2xl font-bold">
        {{ formatNumber(found.balance, 2) }}
      </p>
    </div>

    <p
      v-if="error"
      role="alert"
      class="mb-3 rounded-rpos bg-danger/10 p-3 text-xs text-danger"
    >
      {{ error }}
    </p>

    <div class="flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.cancel") }}
      </button>
      <button
        v-if="!found"
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
        :disabled="!canSend"
        @click="check"
      >
        {{ t("giftCard.check") }}
      </button>
      <button
        v-else
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast"
        @click="use"
      >
        {{ t("action.done") }}
      </button>
    </div>
  </BaseDialog>
</template>
