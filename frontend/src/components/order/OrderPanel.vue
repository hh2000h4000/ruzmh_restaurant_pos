<script setup lang="ts">
import { computed } from "vue";

import { reductionsOn, type OrderDetail, type OrderLine } from "@/api/order";
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
  /**
   * `null` between customers, and the panel still draws (D-059).
   *
   * It was replaced by a placeholder card with a button in the middle of it —
   * so the till changed shape every time a bill was paid, and the cashier's eye
   * had to find the totals again. The bill is furniture: the header, the list
   * and the totals stay where they are, empty, until there is something to put
   * in them.
   */
  order: OrderDetail | null;
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
const shortNumber = computed(() => props.order?.daily_number || 0);

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === props.order?.order_type) ?? null,
);

const typeLabel = computed(() => pick(orderType.value?.title_ar, orderType.value?.title));

/**
 * The two reductions, told apart (`BR-032`, `D-163`).
 *
 * **A promotion spends the shop's money without anybody at the till agreeing to
 * it**, so it is named: a cashier who can only see that the total dropped cannot
 * answer the guest who asks why, and a manager reading the shift cannot tell an
 * offer from someone's decision. The subtraction itself lives in `api/order`,
 * because this screen, the payment screen and the guest's screen all do it.
 */
const reductions = computed(() => reductionsOn(props.order ?? null));

/** Where this order is: the table if it sits at one, else nothing to say. */
const seat = computed(() =>
  props.order?.table_number ? t("card.table", { number: props.order.table_number }) : "",
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
  const known = KNOWN_STATUSES.find((candidate) => candidate === props.order?.status);
  return known ? t(`status.${known}`) : (props.order?.status ?? "");
});

/** Bare figures: the currency is stated once, on the total. */
function money(value: number | undefined): string {
  return formatNumber(value ?? 0, 2);
}
</script>

<template>
  <section
    class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-rpos-lg border border-line bg-surface"
  >
    <!--
      Two lines, the way the reference reads: the number and the state, then
      what kind of sale it is and who it is for.
    -->
    <!-- The same four rows whether a bill is in hand or not, so the panel does
         not resize under the cashier's eye between customers (D-059). -->
    <header
      v-if="order"
      class="border-b border-line px-[22px] pb-[18px] pt-5"
    >
      <div class="flex items-start justify-between gap-3">
        <p class="rpos-numeric text-[26px] font-medium leading-none tracking-tight">
          {{ formatNumber(shortNumber) }}
        </p>
        <p
          class="flex items-center gap-2 text-sm"
          :class="STATUS_CLASS[order.status] ?? 'text-muted'"
        >
          <span class="h-[7px] w-[7px] shrink-0 rounded-full bg-current" />
          {{ statusLabel }}
        </p>
      </div>

      <div class="mt-2.5 flex items-center justify-between gap-3">
        <p class="flex min-w-0 items-center gap-2 truncate text-sm text-muted">
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

      <!-- FR-2.1 step 4 — where it goes, when it goes anywhere. On the bill
           rather than behind the customer dialog: a driver reads this. -->
      <p
        v-if="order.delivery_address_line"
        class="mt-1 flex items-center gap-1.5 truncate text-xs text-muted"
      >
        <AppIcon
          name="home"
          :size="14"
          class="shrink-0"
        />
        <span class="truncate">{{ order.delivery_address_line }}</span>
      </p>

      <p class="rpos-numeric mt-2 truncate text-xs text-muted">
        {{ order.order_name }}
      </p>
    </header>

    <!-- Between customers. The same height as the strip above, so the list
         below it does not jump when a bill opens. -->
    <header
      v-else
      class="border-b border-line px-[22px] pb-[18px] pt-5"
    >
      <p class="rpos-numeric text-[26px] font-medium leading-none text-muted opacity-30">
        —
      </p>
      <p class="mt-2.5 text-sm text-muted">
        {{ t("panel.noOrder") }}
      </p>
      <p class="mt-2 text-xs text-muted opacity-0">
        &nbsp;
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
        :promotion-label="reductions.promotion?.title"
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
          {{ order ? t("panel.empty") : t("panel.startHint") }}
        </p>
        <p
          v-if="order"
          class="mt-1 text-xs text-muted"
        >
          {{ t("panel.swipeHint") }}
        </p>
      </li>
    </ul>

    <dl class="space-y-3 border-t border-line px-[22px] pb-5 pt-[18px]">
      <div class="flex justify-between text-muted">
        <dt>{{ t("totals.subtotal") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order?.subtotal) }}
        </dd>
      </div>
      <div
        v-if="reductions.promotion"
        class="flex justify-between gap-3 text-status-available"
      >
        <dt class="truncate">
          {{ reductions.promotion.title }}
        </dt>
        <dd class="rpos-numeric shrink-0">
          −{{ money(reductions.promotion.amount) }}
        </dd>
      </div>
      <div
        v-if="reductions.discount"
        class="flex justify-between text-status-available"
      >
        <dt>{{ t("totals.discount") }}</dt>
        <dd class="rpos-numeric">
          −{{ money(reductions.discount) }}
        </dd>
      </div>
      <div class="flex justify-between text-muted">
        <dt>{{ t("totals.tax") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order?.tax_amount) }}
        </dd>
      </div>
      <div class="flex items-baseline justify-between border-t border-line pt-3">
        <dt class="text-base font-semibold">
          {{ t("totals.total") }}
        </dt>
        <dd class="rpos-numeric text-[30px] font-medium tracking-tighter">
          {{ money(order?.total_amount) }}
        </dd>
      </div>

      <!-- The action the whole screen exists to reach, under the figure the
           customer is being told, where the cashier is already looking. -->
      <button
        type="button"
        class="mt-1 flex min-h-[4.125rem] w-full items-center justify-center gap-2.5 rounded-rpos-lg bg-primary text-[17px] font-medium text-primary-contrast shadow-primary transition duration-200 ease-rpos hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        :disabled="!canPay"
        @click="emit('pay')"
      >
        <AppIcon
          name="card"
          :size="22"
          class="opacity-85"
        />
        {{ t("order.payWithTotal", { total: money(order?.total_amount) }) }}
      </button>
    </dl>
  </section>
</template>
