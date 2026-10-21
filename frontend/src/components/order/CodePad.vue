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

/**
 * **The keyboard's own rows** (`D-382`): digits on top, then Q to P, A to L and
 * Z to M — the order every cashier's thumb already knows from the phone in
 * their pocket. It was A to Z in rows of nine, which nobody has typed on, so
 * every letter was a search.
 */
const ROWS = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"].map((row) => [...row]);

function press(key: string): void {
  if (props.maxLength && props.value.length >= props.maxLength) return;
  emit("update", props.value + key);
}
</script>

<template>
  <!-- Left to right whatever the page direction, like every other pad here: a
       keyboard laid out by the locale comes out backwards and is not a keyboard
       anybody has used (`FR-17`). Every key is a tenth of the widest row, and
       the shorter rows sit centred under it, as on a keyboard. -->
  <div
    v-if="shown"
    class="rpos-pad-tray flex flex-col gap-1.5"
    dir="ltr"
  >
    <div
      v-for="(row, index) in ROWS"
      :key="index"
      class="flex justify-center gap-1.5"
    >
      <button
        v-for="key in row"
        :key="key"
        type="button"
        class="rpos-pad-key h-11 w-[calc((100%-9*0.375rem)/10)] shrink-0 text-base"
        @click="press(key)"
      >
        {{ key }}
      </button>

      <!-- Clearing and deleting close the last row, at its ends, where a
           finger reaching for a letter does not land. -->
      <template v-if="index === ROWS.length - 1">
        <button
          type="button"
          class="rpos-pad-key h-11 w-[calc((100%-9*0.375rem)/10)] shrink-0 text-base"
          :aria-label="t('keypad.clear')"
          @click="emit('update', '')"
        >
          c
        </button>
        <button
          type="button"
          class="rpos-pad-key grid h-11 w-[calc((100%-9*0.375rem)/10)] shrink-0 place-items-center"
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
      </template>
    </div>
  </div>
</template>
