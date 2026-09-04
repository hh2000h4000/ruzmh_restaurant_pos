<script setup lang="ts">
/**
 * Which of a table's bills did you mean? (`BR-066`)
 *
 * A table may carry more than one open bill where the branch allows it, and
 * both the tables screen and the order screen's floor pane have to ask the same
 * question. It is asked once, here: two dialogs asking one question are not two
 * features but a defect — the cashier who learns one does not know the other,
 * and fixing one leaves the other broken (`CLAUDE.md` §5.5).
 *
 * Nothing is picked for the cashier. Guessing is how a round of drinks lands on
 * the wrong party's bill, and the two parties only find out at the till.
 */
import type { FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import { dateOnly, t, timeOnly, tn } from "@/i18n";

defineProps<{ table: FloorTable | null }>();
const emit = defineEmits<{ pick: [orderName: string]; close: [] }>();
</script>

<template>
  <BaseDialog
    :open="Boolean(table)"
    :title="t('table.whichBill')"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-2">
      <button
        v-for="bill in table?.orders ?? []"
        :key="bill.name"
        type="button"
        class="min-h-tap rounded-rpos border border-line px-3 text-start"
        @click="emit('pick', bill.name)"
      >
        <span class="rpos-numeric text-lg font-bold">#{{ bill.daily_number }}</span>
        <span class="rpos-numeric ms-2 text-sm opacity-70">
          {{ dateOnly(bill.opened_at) }} {{ timeOnly(bill.opened_at) }} ·
          {{ tn("count.items", bill.item_count) }}
        </span>
      </button>
    </div>
  </BaseDialog>
</template>
