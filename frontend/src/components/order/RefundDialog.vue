<script setup lang="ts">
import { ref, watch } from "vue";

import { getRefund, type RefundDetail } from "@/api/returns";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, t } from "@/i18n";

/**
 * What one refund actually took back (`FR-9.4`, `D-171`).
 *
 * **The refund row on the orders list opened the sale it reverses.** A cashier
 * who returned two dishes off a bill of four tapped the row and got all four,
 * at positive prices — on a row that said *refund* and showed a negative
 * figure. The credit note was never wrong; the screen was reading the other
 * document.
 *
 * **A sheet rather than the till.** A closed sale opens in the till because
 * there is still something to do with it — reprint it, return against it. A
 * credit note is submitted accounting: it is looked at, and printed. Loading it
 * into the till would also throw away the bill the cashier is in the middle of,
 * to show them something they cannot change.
 *
 * Every figure is the document's own and every one of them is negative
 * (`CLAUDE.md` §5.1) — nothing here multiplies anything.
 */
const props = defineProps<{ open: boolean; creditNote: string | null }>();
const emit = defineEmits<{ close: []; reprint: [dailyNumber: number] }>();

const refund = ref<RefundDetail | null>(null);
const failure = ref<string | null>(null);
const loading = ref(false);

watch(
  () => [props.open, props.creditNote],
  async () => {
    if (!props.open || !props.creditNote) return;

    loading.value = true;
    failure.value = null;
    refund.value = null;
    try {
      refund.value = await getRefund(props.creditNote);
    } catch (cause) {
      // **Said, not swallowed.** A sheet that opens empty is indistinguishable
      // from a refund with nothing on it (`D-074`).
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('ret.detailTitle')"
    @close="emit('close')"
  >
    <p
      v-if="loading"
      class="py-6 text-center text-sm text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <p
      v-else-if="failure"
      role="alert"
      class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <template v-else-if="refund">
      <p class="mb-4 text-sm text-muted">
        {{
          t("ret.detailAgainst", {
            number: formatNumber(refund.daily_number),
            against: formatNumber(refund.returns_daily_number),
          })
        }}
      </p>

      <ul class="mb-4 divide-y divide-line border-y border-line">
        <li
          v-for="line in refund.items"
          :key="line.item"
          class="flex items-baseline justify-between gap-3 py-3"
        >
          <span class="min-w-0 truncate text-sm">
            <span class="rpos-numeric text-muted">{{ formatNumber(Math.abs(line.qty)) }}&nbsp;×</span>
            {{ line.item_name }}
          </span>
          <span class="rpos-numeric shrink-0 text-sm text-danger">{{ money(line.amount) }}</span>
        </li>
      </ul>

      <dl class="space-y-2">
        <div class="flex justify-between text-sm text-muted">
          <dt>{{ t("totals.tax") }}</dt>
          <dd class="rpos-numeric">
            {{ money(refund.tax_amount) }}
          </dd>
        </div>
        <div class="flex items-baseline justify-between border-t border-line pt-2">
          <dt class="font-semibold">
            {{ t("ret.detailTotal") }}
          </dt>
          <dd class="rpos-numeric text-2xl font-medium text-danger">
            {{ money(refund.total_amount) }}
          </dd>
        </div>
      </dl>

      <button
        type="button"
        class="mt-5 min-h-[3.25rem] w-full rounded-rpos border border-line text-sm font-medium transition-colors duration-100 ease-rpos hover:border-primary"
        @click="emit('reprint', refund.daily_number)"
      >
        {{ t("print.receiptAgain") }}
      </button>
    </template>
  </BaseDialog>
</template>
