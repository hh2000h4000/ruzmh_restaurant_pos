<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
  createReturn,
  getReturnable,
  previewReturn,
  type Returnable,
  type ReturnLine,
  type ReturnReason,
} from "@/api/returns";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, t, type MessageKey } from "@/i18n";

/**
 * Sending part of a paid bill back (FR-9.2, D-064).
 *
 * **A quantity per line, not a checkbox.** A customer sends back one of the two
 * coffees they ordered far more often than they send back a whole ticket, and a
 * tick-box would make the common case impossible.
 *
 * **The refund figure is the server's.** Tapping a quantity asks the backend
 * what the credit note would come to — tax and rounding included — rather than
 * multiplying rate by quantity here and quoting the customer a number the
 * invoice would then disagree with (`CLAUDE.md` §5.1).
 *
 * **What has already come back is shown, not hidden.** A line refunded once
 * offers only what is left, so a second return cannot take more than was sold
 * (`FR-9.3`) and the cashier can see why.
 */
const props = defineProps<{ open: boolean; orderName: string | null }>();
const emit = defineEmits<{ close: []; done: [creditNote: string] }>();

const bill = ref<Returnable | null>(null);
/** Row name → how much of it is going back. */
const chosen = ref<Record<string, number>>({});
/**
 * BR-052 and KSA-10 (D-065) — a code, not a sentence.
 *
 * The reason on a Saudi credit note has to map to one of five triggers ZATCA
 * recognises, and a text box invites "x" typed to get past it. The note beside
 * it is for the humans and is optional.
 */
const reason = ref<ReturnReason | "">("");
const note = ref("");

/** Labels for the codes the server sent. Wording is ours; the list is not. */
const REASON_LABEL: Record<ReturnReason, MessageKey> = {
  goods_returned: "ret.reasonReturned",
  quality_complaint: "ret.reasonQuality",
  wrong_item: "ret.reasonWrongItem",
  price_error: "ret.reasonPrice",
  order_cancelled: "ret.reasonCancelled",
};
const method = ref("");
const refund = ref(0);
const busy = ref(false);
const error = ref<string | null>(null);
const receipt = ref<{ note: string; amount: number } | null>(null);

watch(
  () => props.open,
  async (isOpen) => {
    bill.value = null;
    chosen.value = {};
    reason.value = "";
    note.value = "";
    method.value = "";
    refund.value = 0;
    error.value = null;
    receipt.value = null;
    if (!isOpen || !props.orderName) return;

    busy.value = true;
    try {
      bill.value = await getReturnable(props.orderName);
      // BR-054 — the way it was paid is where the choice *starts*, not what it
      // is limited to (D-066).
      method.value = bill.value.paid_with.length === 1 ? bill.value.paid_with[0].method : "";
    } catch (cause) {
      error.value = message(cause);
    } finally {
      busy.value = false;
    }
  },
);

/** What the customer actually paid with, so the chips can say which. */
const paidWith = computed(() => new Set((bill.value?.paid_with ?? []).map((row) => row.method)));

const lines = computed<ReturnLine[]>(() =>
  Object.entries(chosen.value)
    .filter(([, qty]) => qty > 0)
    .map(([row, qty]) => ({ row, qty })),
);

/** Ask the server what this comes to, whenever the selection changes. */
watch(lines, async (selection) => {
  if (!props.orderName || !selection.length) {
    refund.value = 0;
    return;
  }

  try {
    refund.value = (await previewReturn(props.orderName, selection)).refund_amount;
    error.value = null;
  } catch (cause) {
    error.value = message(cause);
    refund.value = 0;
  }
});

function step(row: string, by: number, limit: number): void {
  const next = Math.min(Math.max((chosen.value[row] ?? 0) + by, 0), limit);
  chosen.value = { ...chosen.value, [row]: next };
}

/** Everything that is left, in one tap — the commonest return is the whole bill. */
function takeAll(): void {
  const all: Record<string, number> = {};
  for (const line of bill.value?.items ?? []) {
    if (line.returnable > 0) all[line.row] = line.returnable;
  }
  chosen.value = all;
}

const canConfirm = computed(
  () => !busy.value && lines.value.length > 0 && Boolean(reason.value && method.value),
);

async function confirm(): Promise<void> {
  if (!canConfirm.value || !props.orderName || !reason.value) return;

  busy.value = true;
  error.value = null;
  try {
    const done = await createReturn({
      order_name: props.orderName,
      items: lines.value,
      reason_code: reason.value,
      note: note.value.trim() || null,
      refund_method: method.value,
    });

    receipt.value = { note: done.credit_note, amount: done.refund_amount };
    emit("done", done.credit_note);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('ret.title')"
    :dismissible="true"
    @close="emit('close')"
  >
    <p
      v-if="error"
      role="alert"
      class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ error }}
    </p>

    <!-- Done. The amount to hand back is the whole message. -->
    <template v-if="receipt">
      <div class="mb-4 rounded-rpos bg-background p-5 text-center">
        <p class="mb-1 text-sm font-semibold text-muted">
          {{ t("ret.refunded") }}
        </p>
        <p class="rpos-numeric mb-2 text-3xl font-bold text-status-available">
          {{ money(receipt.amount) }}
        </p>
        <p class="rpos-numeric text-xs text-muted">
          {{ receipt.note }}
        </p>
        <p class="mt-2 text-xs text-muted">
          {{ t("ret.whereItLives") }}
        </p>
      </div>
      <button
        type="button"
        class="min-h-tap w-full rounded-rpos bg-primary font-bold text-primary-contrast"
        @click="emit('close')"
      >
        {{ t("action.back") }}
      </button>
    </template>

    <template v-else-if="bill">
      <!--
        What has already gone back, and its credit-note number (D-068).
        The server sent this from the start and the screen was throwing it away,
        so a cashier asked where a refund went and the till had no answer — even
        though it had one in hand.
      -->
      <div
        v-if="bill.returns.length"
        class="mb-3 rounded-rpos bg-background p-3"
      >
        <p class="mb-2 text-xs font-semibold text-muted">
          {{ t("ret.previous") }}
        </p>
        <div
          v-for="credit in bill.returns"
          :key="credit.name"
          class="flex items-center justify-between gap-3 text-sm"
        >
          <span class="rpos-numeric min-w-0 truncate text-muted">{{ credit.name }}</span>
          <span class="rpos-numeric shrink-0 font-semibold">{{
            money(Math.abs(credit.grand_total))
          }}</span>
        </div>
      </div>

      <p
        v-if="bill.fully_returned"
        class="rounded-rpos bg-background p-4 text-center text-sm text-muted"
      >
        {{ t("ret.allReturned") }}
      </p>

      <template v-else>
        <div class="mb-3 flex items-center justify-between gap-3">
          <p class="text-sm text-muted">
            {{ t("ret.body") }}
          </p>
          <button
            type="button"
            class="shrink-0 text-sm font-semibold text-primary underline"
            @click="takeAll"
          >
            {{ t("ret.takeAll") }}
          </button>
        </div>

        <div class="mb-3 max-h-64 space-y-1.5 overflow-y-auto">
          <div
            v-for="line in bill.items"
            :key="line.row"
            class="flex items-center gap-3 rounded-rpos bg-background px-3 py-2"
            :class="line.returnable <= 0 ? 'opacity-50' : ''"
          >
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold">{{ line.item_name }}</span>
              <span class="rpos-numeric block text-xs text-muted">
                {{ money(line.rate) }} ·
                {{ t("ret.leftOf", { left: formatNumber(line.returnable), sold: formatNumber(line.qty) }) }}
              </span>
            </span>

            <span
              v-if="line.returnable > 0"
              class="flex shrink-0 items-center gap-1"
              dir="ltr"
            >
              <button
                type="button"
                class="grid h-9 w-9 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-surface disabled:opacity-30"
                :disabled="!chosen[line.row]"
                :aria-label="t('picker.qtyLess')"
                @click="step(line.row, -1, line.returnable)"
              >
                <AppIcon
                  name="minus"
                  :size="18"
                />
              </button>
              <span class="rpos-numeric w-7 text-center font-bold">{{
                formatNumber(chosen[line.row] ?? 0)
              }}</span>
              <button
                type="button"
                class="grid h-9 w-9 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-surface disabled:opacity-30"
                :disabled="(chosen[line.row] ?? 0) >= line.returnable"
                :aria-label="t('picker.qtyMore')"
                @click="step(line.row, 1, line.returnable)"
              >
                <AppIcon
                  name="plus"
                  :size="18"
                />
              </button>
            </span>
          </div>
        </div>

        <!--
          BR-054, D-066 — always shown, and it lists **every** method the till
          has, not only the one the bill was paid with. A card terminal that is
          down, or a customer who would rather take the cash, are ordinary
          evenings; the original is the default, not the limit.
        -->
        <div class="mb-3">
          <p class="mb-1.5 text-sm font-semibold text-muted">
            {{ t("ret.method") }}
          </p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="option in bill.methods"
              :key="option"
              type="button"
              class="min-h-tap rounded-full px-4 text-sm font-semibold transition duration-200 ease-rpos"
              :class="method === option ? 'bg-primary text-primary-contrast' : 'bg-background text-muted'"
              :aria-pressed="method === option"
              @click="method = option"
            >
              {{ option }}
              <!-- Which one the customer actually paid with, so the default is
                   not a mystery. -->
              <span
                v-if="paidWith.has(option)"
                class="opacity-70"
              >· {{ t("ret.asPaid") }}</span>
            </button>
          </div>
        </div>

        <!-- BR-052 and KSA-10 (D-065) — one of five, chosen not typed. -->
        <p class="mb-1.5 text-sm font-semibold text-muted">
          {{ t("ret.reason") }}
        </p>
        <div class="mb-3 flex flex-wrap gap-2">
          <button
            v-for="code in bill.reasons"
            :key="code"
            type="button"
            class="min-h-tap rounded-full px-4 text-sm font-semibold transition duration-200 ease-rpos"
            :class="reason === code ? 'bg-primary text-primary-contrast' : 'bg-background text-muted'"
            :aria-pressed="reason === code"
            @click="reason = code"
          >
            {{ t(REASON_LABEL[code]) }}
          </button>
        </div>

        <!-- For the humans. The code above is what a validator reads. -->
        <input
          v-model="note"
          type="text"
          class="mb-3 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          :placeholder="t('ret.note')"
        >

        <p class="mb-4 flex items-center justify-between rounded-rpos bg-background p-3">
          <span class="text-sm font-semibold text-muted">{{ t("ret.refund") }}</span>
          <span class="rpos-numeric text-xl font-bold text-primary">{{ money(refund) }}</span>
        </p>

        <div class="flex gap-2">
          <button
            type="button"
            class="min-h-tap flex-1 rounded-rpos border border-line"
            @click="emit('close')"
          >
            {{ t("action.undo") }}
          </button>
          <button
            type="button"
            class="min-h-tap flex-1 rounded-rpos bg-danger font-bold text-white disabled:opacity-40"
            :disabled="!canConfirm"
            @click="confirm"
          >
            {{ t("ret.confirm") }}
          </button>
        </div>
      </template>
    </template>

    <p
      v-else
      class="p-4 text-center text-sm text-muted"
    >
      {{ t("common.loading") }}
    </p>
  </BaseDialog>
</template>
