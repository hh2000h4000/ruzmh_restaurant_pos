<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

import { applyCoupon, removeCoupon } from "@/api/payment";
import BaseDialog from "@/components/BaseDialog.vue";
import CodePad from "@/components/order/CodePad.vue";
import { t } from "@/i18n";

/**
 * The guest's coupon code — asked once, from wherever it is presented (`D-248`).
 *
 * **One dialog, two doors** (`CLAUDE.md` §5.5). The guest mentions the code
 * while ordering as often as at the till, so it is reachable from the order
 * screen's More menu *and* from the payment screen beside the manual offer. The
 * question is the same in both — *what is the code* — so it is asked once here
 * rather than written twice and allowed to drift.
 *
 * **The server owns every rule.** Expired, switched off, used up, or for an
 * offer that is not running: each is a different problem the cashier can act on,
 * and each sentence is the server's own rather than a guess made here (§5.4).
 *
 * **And the discount is the promotion's, not the coupon's.** The code unlocks an
 * offer and the offer prices the bill, so nothing here computes money.
 *
 * **Typed on screen, or scanned** (`D-250`). A till in kiosk mode raises no soft
 * keyboard, so the keys are drawn — and the field still takes focus and still
 * applies on Enter, which is all a keyboard-wedge scanner needs to work here
 * with no integration at all.
 */
const props = defineProps<{
  open: boolean;
  orderName: string | null;
  /** The code already on the bill, so it can be shown and taken back off. */
  applied?: { name: string; code: string; campaign: string } | null;
}>();

const emit = defineEmits<{ close: []; changed: [] }>();

const code = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const field = ref<HTMLInputElement | null>(null);

const canSend = computed(() => code.value.trim().length > 0 && !busy.value);

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;
    code.value = "";
    error.value = null;

    // **Focused on open, for the scanner's sake.** A keyboard-wedge reader types
    // into whatever holds focus; without this the scan lands nowhere and the
    // cashier sees a dead trigger rather than a filled field.
    await nextTick();
    field.value?.focus();
  },
);

async function apply(): Promise<void> {
  if (!props.orderName || !canSend.value) return;

  busy.value = true;
  error.value = null;
  try {
    await applyCoupon({ order_name: props.orderName, code: code.value.trim() });
    emit("changed");
    emit("close");
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(): Promise<void> {
  if (!props.orderName || busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    await removeCoupon(props.orderName);
    emit("changed");
    emit("close");
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
    :title="t('coupon.title')"
    @close="emit('close')"
  >
    <p class="mb-4 text-xs text-subtle">
      {{ t("coupon.body") }}
    </p>

    <!-- `D-074` — the bill already carrying a code says so, rather than leaving
         the cashier to wonder why a second one is refused. -->
    <div
      v-if="applied"
      class="mb-4 flex items-center justify-between gap-2 rounded-rpos bg-background p-3"
    >
      <span class="text-sm">
        <span class="font-medium">{{ applied.code }}</span>
        <span
          v-if="applied.campaign"
          class="text-subtle"
        >
          · {{ applied.campaign }}
        </span>
      </span>
      <button
        type="button"
        class="min-h-tap rounded-rpos px-3 text-sm text-danger"
        :disabled="busy"
        @click="remove"
      >
        {{ t("action.remove") }}
      </button>
    </div>

    <input
      ref="field"
      :value="code"
      type="text"
      autocapitalize="characters"
      autocomplete="off"
      class="mb-3 w-full rounded-rpos border border-line bg-background p-3 text-center text-lg tracking-widest"
      :placeholder="t('coupon.placeholder')"
      @input="code = ($event.target as HTMLInputElement).value.toUpperCase()"
      @keyup.enter="apply"
    >

    <CodePad
      class="mb-3"
      :value="code"
      @update="code = $event"
    />

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
        :disabled="!canSend"
        @click="apply"
      >
        {{ t("coupon.apply") }}
      </button>
    </div>
  </BaseDialog>
</template>
