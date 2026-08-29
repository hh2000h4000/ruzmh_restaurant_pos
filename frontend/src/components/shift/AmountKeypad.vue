<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { formatNumber, t } from "@/i18n";

/**
 * Typing money with a finger (06 §Design Principles).
 *
 * A till is a touch screen. A `<input type="number">` there depends on the
 * device raising a keyboard — which a kiosk in kiosk mode does not, and which
 * on a tablet covers half the dialog when it does. So the digits are on screen,
 * at tap size, where the hand already is.
 *
 * **Digits are Latin, always.** `formatNumber` renders Arabic numerals in
 * Latin script on purpose (`FR-17`), and a keypad that showed ٤ while the field
 * showed 4 would be two alphabets for one number.
 *
 * **A panel, not a dialog.** It replaces the body of the dialog that summoned
 * it rather than opening on top: two stacked `BaseDialog`s both listen for
 * Escape, so one key would close the keypad and the shift dialog behind it.
 */
const props = defineProps<{
  /** Starting value, as typed — not formatted. */
  value: string;
}>();

const emit = defineEmits<{ close: []; confirm: [value: string] }>();

/** What has been tapped so far. A string, because "1." is a real halfway state. */
const draft = ref(props.value === "0" ? "" : props.value);

watch(
  () => props.value,
  (value) => {
    draft.value = value === "0" ? "" : value;
  },
);

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as const;

/** Two decimals is the currency's precision; more is a typo, not an amount. */
const decimals = computed(() => draft.value.split(".")[1]?.length ?? 0);

function press(key: string): void {
  if (key === "." && draft.value.includes(".")) return;
  if (key !== "." && decimals.value >= 2) return;
  if (key === "." && !draft.value) {
    draft.value = "0.";
    return;
  }

  draft.value += key;
}

/** One tap back, then a long list of taps forward — so clear is one key. */
function clear(): void {
  draft.value = "";
}

function back(): void {
  draft.value = draft.value.slice(0, -1);
}

const preview = computed(() => formatNumber(Number(draft.value) || 0, 2));

function confirm(): void {
  emit("confirm", draft.value || "0");
}
</script>

<template>
  <div>
    <p
      class="rpos-numeric mb-4 rounded-rpos bg-background px-4 py-4 text-center text-3xl font-bold"
      dir="ltr"
    >
      {{ preview }}
    </p>

    <div class="mb-4 grid grid-cols-3 gap-2">
      <button
        v-for="key in KEYS"
        :key="key"
        type="button"
        class="rpos-numeric h-16 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        @click="press(key)"
      >
        {{ key }}
      </button>

      <button
        type="button"
        class="grid h-16 place-items-center rounded-rpos bg-background text-muted transition duration-200 ease-rpos hover:bg-danger/10 hover:text-danger"
        :aria-label="t('keypad.clear')"
        @click="clear"
      >
        C
      </button>
      <button
        type="button"
        class="rpos-numeric h-16 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        @click="press('0')"
      >
        0
      </button>
      <button
        type="button"
        class="rpos-numeric h-16 rounded-rpos bg-background text-2xl font-bold transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
        @click="press('.')"
      >
        .
      </button>
    </div>

    <div class="flex gap-2">
      <button
        type="button"
        class="grid min-h-tap w-16 place-items-center rounded-rpos border border-line"
        :aria-label="t('keypad.back')"
        @click="back"
      >
        <AppIcon
          name="back"
          class="rpos-flip"
          :size="20"
        />
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.undo") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-bold text-primary-contrast"
        @click="confirm"
      >
        {{ t("keypad.done") }}
      </button>
    </div>
  </div>
</template>
