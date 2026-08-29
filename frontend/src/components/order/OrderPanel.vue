<script setup lang="ts">
import { computed } from "vue";

import type { OrderDetail, OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import OrderLineRow from "@/components/order/OrderLineRow.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * The order side of Screen 3: who this bill belongs to, the lines, the totals.
 *
 * Three rows — the identity strip, a list that scrolls, totals pinned at the
 * foot — so the total never leaves the screen no matter how long the order
 * gets. That is the figure the customer is being told.
 *
 * **The bill names itself.** The reference system puts the order number, the
 * status, the type and the customer at the head of the bill rather than in the
 * window's title bar, and it is right: when a cashier reads a number out or
 * hands the screen round, they are looking at the bill, not at the chrome
 * above it.
 *
 * Every figure here came from the server. Nothing on this screen adds up a
 * column (`CLAUDE.md` §5.1); if it did, the customer could be told one number
 * and charged another.
 */
const props = defineProps<{
  order: OrderDetail;
  lines: OrderLine[];
  busy?: boolean;
  /** `false` while the order is empty, locked, or already closed. */
  canPay?: boolean;
}>();

const emit = defineEmits<{
  void: [line: OrderLine];
  repeat: [line: OrderLine];
  inspect: [line: OrderLine];
  pay: [];
}>();

const session = useSessionStore();

/**
 * The number a cashier says out loud (FR-2.10).
 *
 * Assigned per branch and restarted on the branch's own cycle, so it stays a
 * number a person can hear. `order_name` is the record id and is printed small
 * beneath it: the short one repeats every day, and the long one is what a
 * search or a refund is traced by.
 */
const shortNumber = computed(() => props.order.daily_number || 0);

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === props.order.order_type) ?? null,
);

const typeLabel = computed(() => pick(orderType.value?.title_ar, orderType.value?.title));

/** Where this order is: the table if it sits at one, else nothing to say. */
const seat = computed(() =>
  props.order.table_number ? t("card.table", { number: props.order.table_number }) : "",
);

const STATUS_CLASS: Record<string, string> = {
  draft: "text-order-draft",
  active: "text-order-active",
  in_kitchen: "text-order-in_kitchen",
  pending_payment: "text-order-pending_payment",
  closed: "text-order-closed",
  cancelled: "text-order-cancelled",
};

const KNOWN_STATUSES = ["draft", "active", "in_kitchen", "pending_payment"] as const;

const statusLabel = computed(() => {
  const known = KNOWN_STATUSES.find((candidate) => candidate === props.order.status);
  return known ? t(`status.${known}`) : props.order.status;
});

/** Bare figures: the currency is stated once, on the total. */
function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <section
    class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-rpos bg-surface shadow-card"
  >
    <!--
      Two lines, the way the reference reads: the number and the state, then
      what kind of sale it is and who it is for.
    -->
    <header class="border-b border-line px-5 py-4">
      <div class="flex items-baseline justify-between gap-3">
        <p class="rpos-numeric text-2xl font-bold leading-none">
          {{ formatNumber(shortNumber) }}
        </p>
        <p
          class="text-sm font-bold uppercase tracking-wide"
          :class="STATUS_CLASS[order.status] ?? 'text-muted'"
        >
          {{ statusLabel }}
        </p>
      </div>

      <div class="mt-1.5 flex items-center justify-between gap-3">
        <p class="flex min-w-0 items-center gap-2 truncate text-sm font-semibold text-muted">
          <span
            v-if="orderType?.color"
            class="h-2.5 w-2.5 shrink-0 rounded-full"
            :style="{ backgroundColor: orderType.color }"
          />
          {{ typeLabel }}
          <span
            v-if="seat"
            class="truncate font-normal"
          >· {{ seat }}</span>
          <span
            v-if="order.cover_count"
            class="rpos-numeric shrink-0 font-normal"
          >· {{ formatNumber(order.cover_count) }} {{ t("panel.covers") }}</span>
        </p>

        <!--
          Whoever this bill is for: the name to call out if one was written
          (FR-2.11), else the Customer if one was chosen. Both at once would
          only make the cashier read two names for one order.
        -->
        <p
          v-if="order.call_name || order.customer_name || order.customer"
          class="min-w-0 shrink-0 truncate text-sm font-semibold text-primary"
        >
          {{ order.call_name || order.customer_name || order.customer }}
        </p>
      </div>

      <p class="rpos-numeric mt-1 truncate text-xs text-muted">
        {{ order.order_name }}
      </p>
    </header>

    <ul
      class="min-h-0 divide-y divide-line overflow-y-auto"
      :aria-label="t('panel.title')"
    >
      <OrderLineRow
        v-for="line in lines"
        :key="line.idx"
        :line="line"
        :busy="busy"
        @void="emit('void', line)"
        @repeat="emit('repeat', line)"
        @inspect="emit('inspect', line)"
      />

      <li
        v-if="!lines.length"
        class="grid place-items-center px-6 py-16 text-center"
      >
        <span class="mb-3 text-muted opacity-40">
          <AppIcon
            name="receipt"
            :size="44"
          />
        </span>
        <p class="text-muted">
          {{ t("panel.empty") }}
        </p>
        <p class="mt-1 text-xs text-muted">
          {{ t("panel.swipeHint") }}
        </p>
      </li>
    </ul>

    <dl class="space-y-2 border-t border-line p-5">
      <div class="flex justify-between text-muted">
        <dt>{{ t("totals.subtotal") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.subtotal) }}
        </dd>
      </div>
      <div
        v-if="order.discount_amount"
        class="flex justify-between text-status-available"
      >
        <dt>{{ t("totals.discount") }}</dt>
        <dd class="rpos-numeric">
          −{{ money(order.discount_amount) }}
        </dd>
      </div>
      <div class="flex justify-between text-muted">
        <dt>{{ t("totals.tax") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.tax_amount) }}
        </dd>
      </div>
      <div class="flex items-baseline justify-between border-t border-line pt-3">
        <dt class="text-lg font-bold">
          {{ t("totals.total") }}
        </dt>
        <dd class="rpos-numeric text-[26px] font-bold text-primary">
          {{ money(order.total_amount) }}
        </dd>
      </div>

      <!-- The action the whole screen exists to reach, under the figure the
           customer is being told, where the cashier is already looking. -->
      <button
        type="button"
        class="mt-2 flex h-16 w-full items-center justify-center gap-3 rounded-rpos bg-primary text-lg font-bold text-primary-contrast shadow-card transition duration-200 ease-rpos hover:shadow-lift disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!canPay"
        @click="emit('pay')"
      >
        <AppIcon
          name="card"
          :size="24"
        />
        {{ t("order.payWithTotal", { total: money(order.total_amount) }) }}
      </button>
    </dl>
  </section>
</template>
