<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import NoteEditor from "@/components/order/NoteEditor.vue";
import { formatNumber, pick, t } from "@/i18n";

/**
 * Everything that can still be done to one line.
 *
 * Tapping a line on the bill opens this instead of hunting for small buttons on
 * a crowded row — the reference system does the same, and on a touch screen it
 * is the difference between hitting the line you meant and the one below it.
 *
 * **One screen with no scroll, and one Done** (`D-380`), in the keypad's look.
 * It used to open on the line's number and item code, then a note with its own
 * Save, then a quantity with its own Apply, then Back — three ways to keep
 * something, and on a 15" touch screen the quantity and the void had scrolled
 * off. Now: the dish and its amount, the count, the notes in a box of their
 * own that scrolls inside itself, and Done keeps the count and the note
 * together. Tapping outside keeps nothing.
 *
 * What is *not* here is as deliberate as what is. Per-item discounts, recipes,
 * stock and a scale reading all appear on the reference screen; each needs a
 * backend that does not exist yet, and a button that does nothing is worse than
 * no button.
 */
const props = defineProps<{ line: OrderLine | null; busy?: boolean }>();

const emit = defineEmits<{
  close: [];
  /** What changed, and only that: a count the kitchen has is not sent. */
  save: [idx: number, change: { qty?: number; notes?: string | null }];
  void: [line: OrderLine];
}>();

const qty = ref(1);
const notes = ref("");

watch(
  () => props.line,
  (line) => {
    qty.value = line ? line.qty : 1;
    notes.value = line?.notes ?? "";
  },
  { immediate: true },
);

/**
 * FR-2.9 — every line takes a note, and this is where.
 *
 * It used to be reachable only through the modifier popup, which opens only for
 * items that have modifier groups: a plain dish could never be given one.
 *
 * Unlike the quantity, it stays editable after the kitchen has the line —
 * "actually, no onion" is the commonest thing a customer says once the order is
 * in, and the server corrects the station's ticket to match.
 */
const notesChanged = computed(() => notes.value.trim() !== (props.line?.notes ?? ""));

/** BR-013 — a line the kitchen already has is withdrawn, not edited. */
const editable = computed(() => props.line?.status === "pending");

const modifiers = computed(() =>
  (props.line?.modifiers ?? [])
    .map((modifier) => pick(modifier.option_ar, modifier.option))
    .join(t("common.listSeparator")),
);

function bump(by: number): void {
  qty.value = Math.min(99, Math.max(1, qty.value + by));
}

/** Keep what changed; with nothing changed, Done is just a way out. */
function done(): void {
  const line = props.line;
  if (!line) return;

  const change: { qty?: number; notes?: string | null } = {};
  if (editable.value && qty.value !== line.qty) change.qty = qty.value;
  if (notesChanged.value) change.notes = notes.value.trim() || null;

  if (change.qty === undefined && change.notes === undefined) emit("close");
  else emit("save", line.idx, change);
}
</script>

<template>
  <BaseDialog
    :open="Boolean(line)"
    :title="line?.item_name ?? ''"
    pad
    wide
    @close="emit('close')"
  >
    <template v-if="line">
      <!-- What it is and what it costs, in one line under the name. -->
      <p class="mb-4 flex items-baseline justify-between gap-3 text-sm text-subtle">
        <span class="min-w-0 truncate">{{ modifiers }}</span>
        <span class="rpos-numeric shrink-0 text-xl font-semibold text-content">
          {{ formatNumber(line.amount, 2) }}
        </span>
      </p>

      <div class="grid gap-5 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <!-- The count, while the kitchen has not seen the line. -->
        <div class="flex flex-col gap-2">
          <p
            v-if="!editable"
            class="rounded bg-order-in_kitchen/10 p-3 text-sm text-order-in_kitchen"
          >
            {{ t("line.sentLocked") }}
          </p>
          <template v-else>
            <p class="text-sm text-subtle">
              {{ t("picker.qty") }}
            </p>
            <div class="flex items-center justify-between gap-2 rounded bg-surface p-2">
              <button
                type="button"
                class="grid h-14 w-14 place-items-center rounded bg-background text-content disabled:opacity-40"
                :disabled="qty <= 1 || busy"
                :aria-label="t('picker.qtyLess')"
                @click="bump(-1)"
              >
                <AppIcon name="minus" />
              </button>
              <span
                class="rpos-numeric text-3xl font-medium"
                aria-live="polite"
              >{{ formatNumber(qty) }}</span>
              <button
                type="button"
                class="grid h-14 w-14 place-items-center rounded bg-background text-content disabled:opacity-40"
                :disabled="qty >= 99 || busy"
                :aria-label="t('picker.qtyMore')"
                @click="bump(1)"
              >
                <AppIcon name="plus" />
              </button>
            </div>
          </template>
        </div>

        <!-- FR-2.9 — any item, and still editable once the kitchen has it. -->
        <div class="min-w-0">
          <p class="mb-2 text-sm text-subtle">
            {{ t("mod.note") }}
          </p>
          <NoteEditor
            v-model="notes"
            scope="item"
          />
        </div>
      </div>

      <!-- Withdrawing the dish on one side, keeping the changes on the other. -->
      <div class="mt-5 flex items-center gap-3">
        <button
          type="button"
          class="flex min-h-12 items-center gap-2 rounded px-3 font-medium text-danger transition duration-100 ease-rpos hover:bg-danger/10 disabled:opacity-40"
          :disabled="busy"
          @click="emit('void', line)"
        >
          <AppIcon
            name="trash"
            :size="18"
          />
          {{ t("order.voidItem") }}
        </button>
        <button
          type="button"
          class="rpos-pad-done flex-1"
          :disabled="busy"
          @click="done"
        >
          {{ t("action.done") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
