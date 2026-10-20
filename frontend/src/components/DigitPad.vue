<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n";

/**
 * Ten digits under the finger, for the fields that are nothing but digits.
 *
 * A till in kiosk mode raises no soft keyboard, so a mobile number typed into a
 * bare `<input>` cannot be typed at all — the same problem `AmountKeypad`
 * solves for money (D-049).
 *
 * **Kept separate from that keypad on purpose.** Money has a decimal point, two
 * places and a currency; a phone number has none of those and a length instead.
 * Folding both into one component behind a mode flag would make every change to
 * either one a change to both, and the money keypad is the one that must not
 * break.
 *
 * **The pad runs left to right, always.** A keypad reads 1-2-3 from the left in
 * every locale; laid out by the page direction it would come out 3-2-1 in
 * Arabic, which is not a keypad anybody has used (`FR-17`).
 */
const props = defineProps<{
  /** The digits so far. The owner holds them; this only appends and trims. */
  value: string;
  /** Stop accepting digits past this, when the field has a natural length. */
  maxLength?: number;
}>();

const emit = defineEmits<{ update: [value: string] }>();

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

function press(key: string): void {
  if (props.maxLength && props.value.length >= props.maxLength) return;
  emit("update", props.value + key);
}

function back(): void {
  emit("update", props.value.slice(0, -1));
}

function clear(): void {
  emit("update", "");
}
</script>

<template>
  <!-- The keypad look shared with money and codes (`D-370`): white keys on a
       grey tray. Kept the delete key — a PIN or a phone number is typed
       blind, digit by digit, and one slip should not cost the lot. -->
  <div
    class="rpos-pad-tray grid grid-cols-3 gap-4"
    dir="ltr"
  >
    <button
      v-for="key in KEYS"
      :key="key"
      type="button"
      class="rpos-pad-key"
      @click="press(key)"
    >
      {{ key }}
    </button>

    <button
      type="button"
      class="rpos-pad-key"
      :aria-label="t('keypad.clear')"
      @click="clear"
    >
      c
    </button>
    <button
      type="button"
      class="rpos-pad-key"
      @click="press('0')"
    >
      0
    </button>
    <button
      type="button"
      class="rpos-pad-key grid place-items-center"
      :disabled="!value"
      :aria-label="t('keypad.back')"
      @click="back"
    >
      <AppIcon
        name="back"
        class="rpos-flip"
        :size="20"
      />
    </button>
  </div>
</template>
