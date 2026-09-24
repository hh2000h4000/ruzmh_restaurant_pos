<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n";

/**
 * Letters and digits under the finger, for a code a guest reads out (`D-250`).
 *
 * **A till in kiosk mode raises no soft keyboard**, which is the reason
 * `DigitPad` and `AmountKeypad` exist. A coupon code went into a bare `<input>`
 * beside them, and on a tablet in kiosk mode it could not be typed at all —
 * the rule was already written in this codebase and this component was the one
 * place that ignored it.
 *
 * **The keys are exactly the alphabet the codes are drawn from** (`api/coupons`):
 * no `O`, `0`, `I`, `1` or `L`, because those are the pairs people confuse on a
 * card read down a phone. Offering keys that can never appear in a code would
 * invite a cashier to type a code that cannot exist and then wonder why it was
 * refused.
 *
 * **A hardware scanner needs none of this.** In keyboard-wedge mode it types
 * into whatever holds focus and presses Enter, so the field it feeds is the same
 * one this pad fills — which is why the field keeps focus and Enter applies.
 */
const props = defineProps<{ value: string; maxLength?: number }>();
const emit = defineEmits<{ update: [value: string] }>();

/** Exactly `ALPHABET` in `api/coupons.py`, in reading order. */
const KEYS = [
  ..."ABCDEFGHJKMNPQRSTUVWXYZ",
  ..."23456789",
] as const;

function press(key: string): void {
  if (props.maxLength && props.value.length >= props.maxLength) return;
  emit("update", props.value + key);
}
</script>

<template>
  <!-- Left to right whatever the page direction, like every other pad here: a
       keyboard laid out by the locale comes out backwards and is not a keyboard
       anybody has used (`FR-17`). -->
  <div
    class="grid grid-cols-8 gap-1.5"
    dir="ltr"
  >
    <button
      v-for="key in KEYS"
      :key="key"
      type="button"
      class="rpos-numeric h-11 rounded-rpos border border-line-strong bg-background text-base font-medium transition duration-200 ease-rpos hover:border-primary hover:text-primary"
      @click="press(key)"
    >
      {{ key }}
    </button>

    <button
      type="button"
      class="h-11 rounded-rpos border border-line-strong bg-background text-sm font-medium text-danger transition duration-200 ease-rpos hover:border-danger"
      :aria-label="t('keypad.clear')"
      @click="emit('update', '')"
    >
      C
    </button>
    <button
      type="button"
      class="col-span-2 grid h-11 place-items-center rounded-rpos border border-line-strong bg-background text-muted transition duration-200 ease-rpos hover:border-primary hover:text-primary disabled:opacity-40 disabled:hover:border-line"
      :disabled="!value"
      :aria-label="t('keypad.back')"
      @click="emit('update', value.slice(0, -1))"
    >
      <AppIcon
        name="back"
        class="rpos-flip"
        :size="18"
      />
    </button>
  </div>
</template>
