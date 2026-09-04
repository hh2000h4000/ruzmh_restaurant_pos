<script setup lang="ts">
/**
 * Put another open bill onto this one (`FR-2.12`, `BR-067`).
 *
 * Three columns, the arrangement Foodics uses: this bill on one side, the open
 * bills in the middle, and the chosen one shown in full on the other. The third
 * column is the point — a picker that showed only numbers would have the
 * cashier joining a bill they have not read.
 *
 * **This bill survives and the chosen one is emptied into it.** The cashier is
 * standing on this bill and will carry on working with it, so it keeps its
 * number and its history. The button says which one closes, because joining
 * destroys a document and a cashier must not discover that afterwards.
 *
 * Only open bills are offered. A closed one has been paid and its invoice
 * issued; there is nothing left to join.
 */
import { computed, ref, watch } from "vue";

import * as orderApi from "@/api/order";
import type { OpenOrder, OrderDetail } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import BillCard, { type BillCardLine } from "@/components/order/BillCard.vue";
import { money, t, tn } from "@/i18n";
import { useSessionStore } from "@/stores/session";

const props = defineProps<{ open: boolean; order: OrderDetail | null }>();
const emit = defineEmits<{ done: []; close: [] }>();

const session = useSessionStore();

const candidates = ref<OpenOrder[]>([]);
const chosen = ref<OrderDetail | null>(null);
const busy = ref(false);
const failure = ref<string | null>(null);

/**
 * Bills this one can actually take.
 *
 * The same order type, because the price follows the type and the server
 * refuses the move otherwise (`BR-067`) — offering it and then refusing it
 * would teach the cashier that the screen lies.
 */
const joinable = computed(() =>
  candidates.value.filter(
    (bill) => bill.name !== props.order?.order_name && bill.order_type === props.order?.order_type,
  ),
);

function asLines(bill: OrderDetail | null): BillCardLine[] {
  return (bill?.items ?? [])
    .filter((line) => line.status !== "void")
    .map((line) => ({
      key: line.idx,
      name: line.item_name,
      qty: line.qty,
      amount: line.amount,
      sent: line.status === "sent",
    }));
}

async function load(): Promise<void> {
  const profile = session.profile?.name;
  if (!profile) return;

  try {
    candidates.value = await orderApi.listOrders(profile, "open");
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
}

async function choose(name: string): Promise<void> {
  failure.value = null;
  try {
    chosen.value = await orderApi.getOrder(name);
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
}

watch(
  () => props.open,
  (open) => {
    chosen.value = null;
    failure.value = null;
    if (open) void load();
  },
);

async function join(): Promise<void> {
  if (!props.order || !chosen.value || busy.value) return;

  busy.value = true;
  failure.value = null;
  try {
    await orderApi.mergeBills({
      order_name: chosen.value.order_name,
      into: props.order.order_name,
    });
    emit("done");
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('join.title')"
    wide
    @close="emit('close')"
  >
    <p
      v-if="failure"
      class="mb-3 rounded-rpos bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <div class="grid grid-cols-3 gap-3 h-[55vh]">
      <BillCard
        :title="`#${order?.daily_number ?? ''}`"
        :subtitle="t('join.keeps')"
        :lines="asLines(order)"
        :total="order?.total_amount ?? null"
        :tax="order?.tax_amount ?? null"
      />

      <section class="flex min-h-0 flex-col rounded-rpos border border-line bg-background">
        <header class="border-b border-line px-3 py-2 font-bold">
          {{ t("join.openBills") }}
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto">
          <p
            v-if="!joinable.length"
            class="p-3 text-sm text-muted"
          >
            {{ t("join.noneToJoin") }}
          </p>
          <button
            v-for="bill in joinable"
            :key="bill.name"
            type="button"
            class="flex w-full min-h-tap items-baseline justify-between gap-2 border-b border-line px-3 py-2 text-start last:border-b-0"
            :class="chosen?.order_name === bill.name ? 'bg-surface font-bold' : 'hover:bg-surface'"
            @click="choose(bill.name)"
          >
            <span class="rpos-numeric">#{{ bill.daily_number }}</span>
            <span class="min-w-0 flex-1 truncate text-xs text-muted">
              {{ tn("count.items", bill.item_count) }}
            </span>
            <span class="rpos-numeric">{{ money(bill.total_amount) }}</span>
          </button>
        </div>
      </section>

      <BillCard
        :title="chosen ? `#${chosen.daily_number}` : t('join.pickOne')"
        :subtitle="chosen ? t('join.closes') : undefined"
        :lines="asLines(chosen)"
        :total="chosen?.total_amount ?? null"
        :tax="chosen?.tax_amount ?? null"
        :empty="t('join.pickOne')"
      />
    </div>

    <div class="mt-4 flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.back") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
        :disabled="!chosen || busy"
        @click="join"
      >
        {{
          chosen
            ? t("join.confirm", { from: String(chosen.daily_number), into: String(order?.daily_number ?? "") })
            : t("join.title")
        }}
      </button>
    </div>
  </BaseDialog>
</template>
