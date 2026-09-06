<script setup lang="ts">
import { ref, watch } from "vue";

import BaseDialog from "@/components/BaseDialog.vue";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";

/**
 * A manager, at the till, approving something the cashier may not do alone.
 *
 * **One prompt, wherever it is asked** (`CLAUDE.md` §5.5). A discount above a
 * ceiling and a refund from a counted shift are two rules and one question:
 * *manager, is this allowed?* The payment screen had its own copy of this
 * sheet, the return screen had none at all — so `BR-055` refused the cashier
 * and left them nowhere to type the PIN (`D-147`).
 *
 * The differences that are real become props: what to explain, and **how to
 * verify**, because a discount is approved by a different endpoint from
 * everything else. The PIN box itself is the same in both, and now it is only
 * right once — the payment screen's copy asked for **four** digits while the
 * server has enforced **five** since `D-094`, so a manager could not type their
 * own PIN and the Authorize button never enabled.
 */
const props = defineProps<{
  open: boolean;
  /** Why the till is asking, in the words of the rule that asked. */
  explain: string;
  /** Exchange the PIN for a single-use token, or throw with a message. */
  verify: (pin: string, reason: string) => Promise<string>;
}>();

const emit = defineEmits<{ approved: [token: string]; close: [] }>();

const auth = useAuthStore();

const pin = ref("");
const reason = ref("");
const error = ref<string | null>(null);
const busy = ref(false);

// Never left holding a PIN. Closing, or being reopened for something else, is
// the end of this one — the digits do not outlive the question.
watch(
  () => props.open,
  () => {
    pin.value = "";
    reason.value = "";
    error.value = null;
    busy.value = false;
  },
);

async function approve(): Promise<void> {
  if (busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    emit("approved", await props.verify(pin.value, reason.value.trim()));
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    // Cleared on failure too: a wrong PIN is retyped, never corrected in place.
    pin.value = "";
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="`🔐 ${t('pay.needsManager')}`"
    @close="emit('close')"
  >
    <p class="mb-3 text-sm text-muted">
      {{ explain }}
    </p>

    <label
      for="manager-pin"
      class="mb-1 block text-sm font-medium"
    >{{ t("pay.managerPin") }}</label>
    <input
      id="manager-pin"
      v-model="pin"
      type="password"
      inputmode="numeric"
      autocomplete="off"
      :maxlength="auth.pinLength"
      class="rpos-numeric mb-3 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-center text-2xl tracking-widest"
    >

    <label
      for="manager-reason"
      class="mb-1 block text-sm font-medium"
    >{{ t("pay.reasonRequired") }}</label>
    <input
      id="manager-reason"
      v-model="reason"
      type="text"
      class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
    >

    <p
      v-if="error"
      role="alert"
      class="mb-3 text-sm text-danger"
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
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
        :disabled="busy || pin.length !== auth.pinLength || !reason.trim()"
        @click="approve"
      >
        {{ t("action.authorize") }}
      </button>
    </div>
  </BaseDialog>
</template>
