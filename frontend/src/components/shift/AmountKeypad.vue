<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { t } from "@/i18n";

/**
 * Typing money with a finger (06 §Design Principles, D-049).
 *
 * A till is a touch screen. An `<input type="number">` there waits on the device
 * raising a keyboard — which a tablet in kiosk mode does not, and which when it
 * does appear covers half the dialog it was summoned from. So the digits are on
 * screen, at tap size, where the hand already is.
 *
 * **A panel, not a dialog.** It sits inside whatever asked for it and reports
 * every change, so there is one screen and no confirm step of its own. Making it
 * a second dialog meant the same figure was asked for twice, and two stacked
 * dialogs both answer Escape — one key would have closed the keypad *and* the
 * dialog behind it, losing what had been entered.
 *
 * **Ten digits, a point and `c`.** Halalas are real money — 200.50 is an
 * amount, and BR-024 rounds to the nearest 0.05 — so the decimal point is a key,
 * not an optional extra. No backspace: a figure is four or five keys, and `c`
 * and again is what Foodics' pad offers too (`D-370`).
 *
 * **The pad runs left to right, always.** A calculator keypad reads 1-2-3 from
 * the left in every locale; laid out by the page direction it would come out
 * 3-2-1 in Arabic, which is not a keypad anybody has used. The figures are Latin
 * for the same reason (`FR-17`).
 */
const props = defineProps<{
  /** The value being edited, as typed — not formatted. */
  value: string;
  /** What is being counted, shown over the figure. */
  label?: string;
  /**
   * The figure that stands until a key is pressed, shown quietly (`D-379`):
   * an open-price dish opens on its usual price. The first key starts a new
   * figure rather than typing onto this one, so «25» then «3» is 3, not 253.
   */
  fallback?: string;
}>();

const emit = defineEmits<{ update: [value: string] }>();

/** What has been tapped. A string, because "1." is a real halfway state. */
const draft = ref(props.value === "0" ? "" : props.value);

watch(
  () => props.value,
  (value) => {
    // Only when the owner changed it — otherwise every keystroke echoes back.
    if ((Number(value) || 0) !== (Number(draft.value) || 0)) {
      draft.value = value === "0" ? "" : value;
    }
  },
);

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

/** Two decimals is the currency's precision; more is a typo, not an amount. */
const decimals = computed(() => draft.value.split(".")[1]?.length ?? 0);

function set(next: string): void {
  draft.value = next;
  emit("update", next || "0");
}

function press(key: string): void {
  if (key === "." && draft.value.includes(".")) return;
  if (key !== "." && decimals.value >= 2) return;
  if (key === "." && !draft.value) {
    set("0.");
    return;
  }

  set(draft.value + key);
}

function clear(): void {
  set("");
}

/**
 * What was typed, not what it rounds to.
 *
 * Formatting to two places on every keystroke meant pressing the decimal point
 * changed nothing on screen — "200" and "200." both read 200.00 — so the key
 * looked broken. The figure is formatted where it is *stored*; here it echoes
 * the hand.
 */
const preview = computed(() => draft.value || props.fallback || "0");
</script>

<template>
  <div>
    <p
      v-if="label"
      class="mb-2 text-center text-sm text-subtle"
    >
      {{ label }}
    </p>

    <div
      class="rpos-pad-display"
      dir="ltr"
    >
      <p
        class="rpos-numeric text-2xl font-medium"
        :class="!draft && fallback ? 'text-muted' : ''"
      >
        {{ preview }}
      </p>
    </div>

    <!-- `dir="ltr"` is the point: a keypad is 1-2-3 from the left, everywhere. -->
    <div
      class="rpos-pad-tray mt-4 grid grid-cols-3 gap-4"
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
        class="rpos-pad-key"
        :aria-label="t('keypad.decimal')"
        @click="press('.')"
      >
        .
      </button>
    </div>
  </div>
</template>
