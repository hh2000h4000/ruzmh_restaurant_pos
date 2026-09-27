<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n";

/**
 * Letters and digits under the finger, for a code a guest reads out (`D-250`).
 *
 * **A till in kiosk mode raises no soft keyboard**, which is the reason
 * `DigitPad` and `AmountKeypad` exist. A coupon code went into a bare `<input>`
 * beside them, and on the Windows till in kiosk mode it could not be typed at all —
 * the rule was already written in this codebase and this component was the one
 * place that ignored it.
 *
 * **Every letter and every digit — the generator is the fussy one, not this.**
 * Drawn codes leave out `O`, `0`, `I`, `1` and `L`, because those are the pairs
 * people confuse on a card read down a phone, and that belongs where codes are
 * *made*. Here it was a bug: the moment numbered codes arrived (`D-251`) the
 * user's own example, `10001`, could not be typed at all — he found it on the
 * first screen. A manager may also write a code by hand or upload a sheet of
 * them, so **what this pad must accept is any code that exists**, not any code
 * we would have issued.
 *
 * **A hardware scanner needs none of this.** In keyboard-wedge mode it types
 * into whatever holds focus and presses Enter, so the field it feeds is the same
 * one this pad fills — which is why the field keeps focus and Enter applies.
 */
const props = defineProps<{ value: string; maxLength?: number }>();
const emit = defineEmits<{ update: [value: string] }>();

/**
 * **Only where the device has no keyboard of its own** (`D-277`).
 *
 * The pad exists for the Windows till in kiosk mode, which raises none. A phone
 * or a tablet raises its own the moment the field takes focus, so the pad was a
 * second keyboard under the first — the user's question on seeing it measured
 * on a phone: «ايش بنستفيد… هو اصلا فيه اللوحة تبعه». The Android tablets in
 * `docs/11` run ordinary Chrome with screen pinning, keyboard and all.
 *
 * Numbers are another matter and keep their pads everywhere: an amount or a
 * count is tapped faster on big keys than on a phone's keyboard, which is why
 * Square draws its own on the iPad too.
 */
function hasOwnKeyboard(): boolean {
  const agent = navigator.userAgent;
  if (/Android|iPhone|iPad|iPod/i.test(agent)) return true;
  // iPadOS introduces itself as a Mac. A Mac has no touch points; an iPad has five.
  return /Macintosh/.test(agent) && navigator.maxTouchPoints > 1;
}

const shown = !hasOwnKeyboard();

/** Letters then digits — 36 keys, four rows of nine, no gaps. */
const KEYS = [
  ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ",
  ..."0123456789",
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
    v-if="shown"
    dir="ltr"
  >
    <div class="grid grid-cols-9 gap-1.5">
      <button
        v-for="key in KEYS"
        :key="key"
        type="button"
        class="rpos-numeric h-11 rounded-rpos border border-line-strong bg-background text-base font-medium transition duration-200 ease-rpos hover:border-primary hover:text-primary"
        @click="press(key)"
      >
        {{ key }}
      </button>
    </div>

    <!-- Clearing and deleting sit apart from the characters: a finger reaching
         for a letter must not land on one of them. -->
    <div class="mt-1.5 grid grid-cols-2 gap-1.5">
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
        class="grid h-11 place-items-center rounded-rpos border border-line-strong bg-background text-muted transition duration-200 ease-rpos hover:border-primary hover:text-primary disabled:opacity-40 disabled:hover:border-line"
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
  </div>
</template>
