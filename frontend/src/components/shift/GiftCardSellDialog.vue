<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import { sellGiftCard } from "@/api/giftCard";
import BaseDialog from "@/components/BaseDialog.vue";
import CodePad from "@/components/order/CodePad.vue";
import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import { formatNumber, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Sell a gift card at the counter (`D-256`).
 *
 * **Selling one is not a sale**, which is why it is here beside the drawer's
 * cash rather than on a bill. The guest hands over money and gets a promise: no
 * order, no invoice, no VAT — the tax falls later, on the food they come back
 * for (Article 19; `utils/gift_card.vat_falls_at` says it in full).
 *
 * **The money still lands in the drawer**, so the method it was paid with is
 * asked for and the count expects that much more. Only methods that actually
 * take money are offered: a card cannot be bought with another card, and a
 * delivery platform's credit line is not money in this till (`D-029`).
 *
 * **The number is typed, or scanned.** Same field and same pad as the coupon
 * screen (`D-250`, `D-252`): a kiosk raises no keyboard, and a wedge scanner
 * needs only a focused field.
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; done: [] }>();

const session = useSessionStore();

const number = ref("");
const amount = ref("0");
const method = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const sold = ref<{ card_number: string; balance: number } | null>(null);
const field = ref<HTMLInputElement | null>(null);

/** Only what puts money in the drawer: no credit lines, no gift cards. */
const methods = computed(() =>
  (session.data?.payment_methods ?? []).filter((row) => !row.is_credit && !row.is_gift_card),
);

const value = computed(() => Number(amount.value) || 0);
const canSend = computed(() => number.value.trim().length > 0 && value.value > 0 && !busy.value);

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;
    number.value = "";
    amount.value = "0";
    error.value = null;
    sold.value = null;
    method.value = methods.value.find((row) => row.default)?.mode_of_payment
      || methods.value[0]?.mode_of_payment
      || "";

    await nextTick();
    field.value?.focus();
  },
);

async function confirm(): Promise<void> {
  if (!canSend.value || !session.profile?.name || !method.value) return;

  busy.value = true;
  error.value = null;
  try {
    const card = await sellGiftCard({
      pos_profile: session.profile.name,
      card_number: number.value.trim(),
      amount: value.value,
      mode_of_payment: method.value,
    });
    // Shown rather than closed on: the cashier reads the balance back to the
    // guest, and a screen that vanished would leave them nothing to read.
    sold.value = { card_number: card.card_number, balance: card.balance };
    emit("done");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('giftCard.sellTitle')"
    :wide="!sold"
    @close="emit('close')"
  >
    <!-- Done: the number and what is on it, to read back across the counter. -->
    <template v-if="sold">
      <p class="mb-2 text-xs text-subtle">
        {{ t("giftCard.soldBody") }}
      </p>
      <div class="mb-4 rounded-rpos bg-background p-4 text-center">
        <p
          class="rpos-numeric text-2xl font-bold tracking-widest"
          dir="ltr"
        >
          {{ sold.card_number }}
        </p>
        <p class="rpos-numeric mt-1 text-sm text-muted">
          {{ formatNumber(sold.balance, 2) }}
        </p>
      </div>
      <button
        type="button"
        class="min-h-tap w-full rounded-rpos bg-primary font-medium text-primary-contrast"
        @click="emit('close')"
      >
        {{ t("action.done") }}
      </button>
    </template>

    <template v-else>
      <p class="mb-4 text-xs text-subtle">
        {{ t("giftCard.sellBody") }}
      </p>

      <!-- Two keypads, side by side where the till has the width: stacked,
           they ran past the screen and hid the button that sells. -->
      <div class="grid gap-4 lg:grid-cols-2">
        <div>
          <input
            ref="field"
            :value="number"
            type="text"
            autocapitalize="characters"
            autocomplete="off"
            dir="ltr"
            class="mb-3 w-full rounded-rpos border border-line bg-background p-3 text-center text-lg tracking-widest"
            :placeholder="t('giftCard.numberPlaceholder')"
            @input="number = ($event.target as HTMLInputElement).value.toUpperCase()"
          >

          <CodePad
            :value="number"
            @update="number = $event"
          />
        </div>

        <AmountKeypad
          :value="amount"
          :label="t('giftCard.amount')"
          @update="amount = $event"
        />
      </div>
    </template>

    <template
      v-if="!sold"
      #footer
    >
      <!-- What the guest paid with. The drawer counts it, so it has to be
           asked rather than assumed. -->
      <div class="mb-3 grid grid-cols-2 gap-2">
        <button
          v-for="row in methods"
          :key="row.mode_of_payment"
          type="button"
          class="min-h-tap rounded-rpos border font-medium transition-colors duration-100 ease-rpos"
          :class="
            method === row.mode_of_payment
              ? 'border-primary bg-primary text-primary-contrast'
              : 'border-line bg-background text-content'
          "
          :aria-pressed="method === row.mode_of_payment"
          @click="method = row.mode_of_payment"
        >
          {{ row.mode_of_payment }}
        </button>
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
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="!canSend || !method"
          @click="confirm"
        >
          {{ t("giftCard.sell") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
