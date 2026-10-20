<script setup lang="ts">
/**
 * How much of the bill this method is taking (`FR-10.2`, `D-124`).
 *
 * **Method first, then amount.** Tapping a method used to drop a row on the
 * screen prefilled with the balance and two number fields to correct it — which
 * is a form, not a till. A second tap made a row worth nothing, and the server
 * refused it after the cashier had stopped looking (`D-123`). Asking for the
 * amount at the moment the method is chosen makes an empty tender impossible to
 * express.
 *
 * **The first option is always what is still owed**, because that is what
 * happens nearly every time: one tap and the bill is paid. The round notes
 * under it are for cash only — a card cannot be handed 100 for a 35 bill — and
 * they are how change gets calculated without a separate field to type it in.
 *
 * Taken from Foodics, which the user uses and whose flow this follows exactly.
 */
import { computed, ref, watch } from "vue";

import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { methodName, money, t } from "@/i18n";

/**
 * Notes a customer actually hands over. Not a computation — a list of the
 * things in a wallet — so it lives here rather than being asked of the server.
 */
const NOTES = [5, 10, 50, 100, 200, 500];

/** How many round notes above the amount are worth offering. Two is Foodics'. */
const DENOMINATIONS = 2;

const props = defineProps<{
  /** The method being tendered, or `null` while the sheet is shut. */
  method: string | null;
  /** What is still owed — or this person's share, when the table is splitting. */
  due: number;
  /** Only cash can be handed more than the bill. */
  isCash: boolean;
}>();

const emit = defineEmits<{ pick: [amount: number]; close: [] }>();

const typing = ref(false);
const draft = ref("");

/** The due amount first, then the notes a customer might hand over. */
const options = computed(() => {
  const due = Math.max(props.due, 0);
  if (!props.isCash) return [due];

  return [due, ...NOTES.filter((note) => note > due).slice(0, DENOMINATIONS)];
});

const custom = computed(() => Number(draft.value) || 0);

/** Shut the keypad every time the sheet opens: last time's figure is a trap. */
watch(
  () => props.method,
  () => {
    typing.value = false;
    draft.value = "";
  },
);
</script>

<template>
  <BaseDialog
    :open="Boolean(method)"
    :title="methodName(method)"
    pad
    @close="emit('close')"
  >
    <!-- The amounts, or the keypad for one that is not there — one at a time,
         in the keypad's narrow shape (`D-370`). Nothing to cancel: the backdrop
         closes the sheet and nothing is taken until an amount is picked. -->
    <div
      v-if="!typing"
      class="flex flex-col gap-3 pt-2"
    >
      <button
        v-for="(amount, index) in options"
        :key="amount"
        type="button"
        class="rpos-numeric min-h-14 rounded text-xl font-medium"
        :class="index === 0 ? 'bg-primary text-primary-contrast' : 'bg-surface'"
        @click="emit('pick', amount)"
      >
        {{ money(amount) }}
      </button>

      <button
        type="button"
        class="rpos-pad-done"
        @click="typing = true"
      >
        {{ t("pay.customAmount") }}
      </button>
    </div>

    <div
      v-else
      class="flex flex-col gap-4"
    >
      <AmountKeypad
        :value="draft"
        @update="draft = $event"
      />
      <button
        type="button"
        class="rpos-pad-done"
        :disabled="custom <= 0"
        @click="emit('pick', custom)"
      >
        {{ t("action.done") }}
      </button>
    </div>
  </BaseDialog>
</template>
