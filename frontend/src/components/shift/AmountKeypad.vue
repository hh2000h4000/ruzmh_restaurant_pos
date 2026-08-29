<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
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
 * **Ten digits and a point.** Halalas are real money — 200.50 is an amount, and
 * BR-024 rounds to the nearest 0.05 — so the decimal point is a key, not an
 * optional extra. Backspace sits beside the figure instead, where a calculator
 * app puts it.
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

function back(): void {
  set(draft.value.slice(0, -1));
}

/**
 * What was typed, not what it rounds to.
 *
 * Formatting to two places on every keystroke meant pressing the decimal point
 * changed nothing on screen — "200" and "200." both read 200.00 — so the key
 * looked broken. The figure is formatted where it is *stored*; here it echoes
 * the hand.
 */
const preview = computed(() => draft.value || "0");
</script>

<template>
  <div>
    <p
      v-if="label"
      class="mb-1.5 text-sm font-semibold text-muted"
    >
      {{ label }}
    </p>

    <!--
      Backspace lives with the figure, not in the pad. The pad is ten digits and
      a decimal point — a calculator's shape, which a hand already knows — and
      taking a key out of it to make room is how the point went missing.
    -->
    <div
      class="mb-3 flex items-center gap-2 rounded-rpos bg-background px-3 py-3"
      dir="ltr"
    >
      <p class="rpos-numeric flex-1 text-center text-3xl font-bold">
        {{ preview }}
      </p>
      <button
        type="button"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-rpos text-muted transition duration-200 ease-rpos hover:bg-surface hover:text-content disabled:opacity-30"
        :disabled="!draft"
        :aria-label="t('keypad.back')"
        @click="back"
      >
        <AppIcon
          name="back"
          class="rpos-flip"
          :size="22"
        />
      </button>
    </div>

    <!-- `dir="ltr"` is the point: a keypad is 1-2-3 from the left, everywhere. -->
    <div
      class="grid grid-cols-3 gap-2"
      dir="ltr"
    >
      <button
        v-for="key in KEYS"
        :key="key"
        type="button"
        class="rpos-numeric h-14 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        @click="press(key)"
      >
        {{ key }}
      </button>

      <button
        type="button"
        class="h-14 rounded-rpos bg-background text-lg font-bold text-danger transition duration-200 ease-rpos hover:bg-danger/10"
        :aria-label="t('keypad.clear')"
        @click="clear"
      >
        C
      </button>
      <button
        type="button"
        class="rpos-numeric h-14 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        @click="press('0')"
      >
        0
      </button>
      <button
        type="button"
        class="rpos-numeric h-14 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        :aria-label="t('keypad.decimal')"
        @click="press('.')"
      >
        .
      </button>
    </div>
  </div>
</template>
