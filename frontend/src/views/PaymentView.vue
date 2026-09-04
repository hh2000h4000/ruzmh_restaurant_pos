<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import * as paymentApi from "@/api/payment";
import type {
  PaymentLine,
  PaymentMethodOption,
  PaymentSummary,
  TotalsPreview,
} from "@/api/payment";
import BaseDialog from "@/components/BaseDialog.vue";
import TenderSheet from "@/components/order/TenderSheet.vue";
import { formatNumber, t } from "@/i18n";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";

/**
 * Screen 6 — payment.
 *
 * Three columns: methods, discounts, summary (FR-10.1). Every figure comes from
 * the server: the discount is previewed by `preview_totals` before the customer
 * is quoted, and the final amount is the one the Sales Invoice carries
 * (D-018).
 */
const QUICK_DISCOUNTS = [10, 25, 50];

//: Party sizes a table actually asks to split between. Beyond six the guests
//: are usually paying by item, which is a different feature.
const SPLIT_WAYS = [2, 3, 4, 5, 6];

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const orders = useOrderStore();

const orderName = route.params.orderName as string;

const summary = ref<PaymentSummary | null>(null);
const preview = ref<TotalsPreview | null>(null);
const lines = ref<PaymentLine[]>([]);

//: The shares of an even split, and how many have been handed over. Computed
//: on the server (`CLAUDE.md` §5.1) — the last five halalas of 100.00 between
//: three are the whole difficulty.
const shares = ref<number[]>([]);
const settled = ref(0);
const discountType = ref<"percentage" | "amount" | null>(null);
const discountValue = ref(0);
const overrideToken = ref<string | null>(null);
const busy = ref(false);
const failure = ref<string | null>(null);
/**
 * The screen could not be shown at all — no bill, no methods, nothing to fix.
 *
 * Kept apart from `failure` because the two want opposite things. A bill that
 * would not load has nothing to render, so it takes the screen. A refused
 * payment is the cashier's next move: showing it *instead of* the screen threw
 * away the amounts they had just typed and left them a red sentence and a back
 * button (`D-123`).
 */
const loadFailure = ref<string | null>(null);
/**
 * BR-044 — set when the cashier presses Confirm with no shift open, never
 * standing (D-058).
 *
 * The order screen refuses the Pay button first, so reaching here without a
 * shift means a deep link or a shift that closed while this screen was open.
 * Shown above the columns rather than replacing them: the figures stay
 * readable, which is what the cashier is looking at.
 */
const shiftNotice = ref<string | null>(null);
const done = ref<paymentApi.PaymentResult | null>(null);

// Manager approval (FR-10.4, Screen 9)
const askingPin = ref(false);
const pin = ref("");
const pinReason = ref("");
const pinError = ref<string | null>(null);

const due = computed(() => preview.value?.total_amount ?? summary.value?.total_amount ?? 0);
const paid = computed(() => lines.value.reduce((total, line) => total + (line.amount || 0), 0));
const remaining = computed(() => round(due.value - paid.value));
const tendered = computed(() =>
  lines.value.reduce((total, line) => total + (line.tendered ?? line.amount ?? 0), 0),
);
const change = computed(() => (remaining.value <= 0 ? round(tendered.value - due.value) : 0));

/** True while a share is still waiting to be handed over. */
const splitting = computed(() => settled.value < shares.value.length);

const forcedMethod = computed(
  () => summary.value?.payment_methods.find((method) => method.is_forced)?.payment_method ?? null,
);
/**
 * The tenders worth sending. A row of zero is not a payment (`D-123`).
 *
 * A cashier who taps a second method after the first took the whole bill gets a
 * row worth nothing, and the old screen let them carry it all the way to
 * Confirm before the server said "a payment amount must be greater than zero" —
 * by which time the message is about a row nobody is looking at any more.
 * Adding one is prevented below; typing one into an existing row is simply
 * ignored, because an empty tender is nothing and refusing the sale over it
 * would be pedantry at a till with a queue.
 */
const payable = computed(() => lines.value.filter((line) => (line.amount || 0) > 0));

/**
 * Whether tapping a method would do anything at all.
 *
 * Nothing left to pay means a new row would be worth zero. Square and Toast do
 * not let an empty tender be created; the button goes quiet instead, and the
 * cashier edits an amount above to free some of the bill up.
 */
const canTakeMore = computed(() => splitting.value || remaining.value > 0.005);

const canConfirm = computed(
  () =>
    !busy.value &&
    payable.value.length > 0 &&
    remaining.value <= 0.005 &&
    !done.value,
);
const needsApproval = computed(() => Boolean(preview.value?.requires_override));

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function money(value: number): string {
  return formatNumber(value, 2);
}

/**
 * A bill this device composed while the line was down (09 §5, D-073).
 *
 * There is no summary to fetch — the order only exists here — so the figures
 * come from the store, which built them with the same arithmetic the server
 * uses (`D-071`). Everything else on this screen is the same.
 */
const offline = computed(() => orders.offline !== null);

onMounted(async () => {
  if (offline.value) {
    const bill = orders.order;
    // The bill is only in memory, so a reload or a fresh tab arrives here with
    // nothing to pay. Said out loud: this screen used to render its header and
    // then nothing at all, which reads as a broken app rather than a lost bill.
    if (!bill) {
      loadFailure.value = t("offline.billGone");
      return;
    }

    summary.value = {
      order_name: bill.order_name,
      subtotal: bill.subtotal,
      discount_amount: bill.discount_amount,
      tax_amount: bill.tax_amount,
      total_amount: bill.total_amount,
      already_paid: false,
      sales_invoice: null,
      // The terminal's own methods. Which ones an order *type* forbids
      // (`BR-023`) is on the server, so the replay is what enforces it — a
      // device that guessed would refuse a method the shop allows.
      payment_methods: (session.data?.payment_methods ?? []).map((row) => ({
        payment_method: row.mode_of_payment,
        is_forced: 0 as const,
        is_default: row.default,
        is_cash: row.is_cash,
      })),
    };
    return;
  }

  try {
    summary.value = await paymentApi.getPaymentSummary(orderName);
    if (summary.value.already_paid) {
      failure.value = t("pay.alreadyPaid", { invoice: summary.value.sales_invoice ?? "" });
    }
  } catch (cause) {
    loadFailure.value = cause instanceof Error ? cause.message : String(cause);
  }
});

/** Re-price on the server whenever the discount changes (FR-10.4). */
watch([discountType, discountValue], async () => {
  overrideToken.value = null;

  if (!discountType.value || !discountValue.value) {
    preview.value = null;
    return;
  }

  try {
    preview.value = await paymentApi.previewTotals(
      orderName,
      discountType.value,
      discountValue.value,
    );
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
});

function setQuickDiscount(percentage: number): void {
  if (discountType.value === "percentage" && discountValue.value === percentage) {
    discountType.value = null;
    discountValue.value = 0;
    return;
  }
  discountType.value = "percentage";
  discountValue.value = percentage;
}

/** The method whose amount is being chosen, or `null` while the sheet is shut. */
const tendering = ref<PaymentMethodOption | null>(null);

/** What the sheet offers first: this person's share, or the whole balance. */
const nextDue = computed(() =>
  splitting.value ? shares.value[settled.value] : Math.max(remaining.value, 0),
);

/**
 * FR-10.2 — take a tender on the method the cashier chose.
 *
 * `amount` is what goes onto the bill and can never exceed what is owed;
 * `tendered` is what was handed over, which for cash may be more and is where
 * the change comes from. A card is never handed more than the bill, so the two
 * are the same figure there.
 */
function takeTender(chosen: number): void {
  const method = tendering.value;
  if (!method) return;

  const amount = round(Math.min(chosen, nextDue.value));
  const tendered = method.is_cash ? chosen : amount;

  const existing = lines.value.find((line) => line.method === method.payment_method);
  if (existing) {
    // Four people paying cash are one cash line: the invoice records what the
    // drawer holds, not who handed over which note. Without this a split would
    // need the same method four times, and the till would reconcile against
    // rows that mean nothing.
    existing.amount = round(existing.amount + amount);
    existing.tendered = round((existing.tendered ?? existing.amount) + tendered);
  } else {
    lines.value.push({ method: method.payment_method, amount, tendered });
  }

  if (splitting.value) settled.value += 1;
  tendering.value = null;
}

function removeMethod(index: number): void {
  lines.value.splice(index, 1);
  // The shares no longer describe what has been taken, and a progress line
  // that lies is worse than none.
  clearSplit();
}

function splitInto(ways: number): void {
  if (!summary.value) return;

  void paymentApi
    .splitEvenly(orderName, ways)
    .then((split) => {
      shares.value = split.shares;
      settled.value = 0;
      lines.value = [];
    })
    .catch((cause) => {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    });
}

function clearSplit(): void {
  shares.value = [];
  settled.value = 0;
}

async function approveDiscount(): Promise<void> {
  if (!summary.value || !preview.value) return;

  pinError.value = null;
  try {
    const approval = await paymentApi.validateDiscountOverride({
      pin: pin.value,
      percentage: preview.value.discount_percentage,
      reason: pinReason.value.trim(),
      branch: session.branch ?? "",
      pos_profile: session.profile?.name ?? "",
      order_name: orderName,
    });

    overrideToken.value = approval.override_token;
    askingPin.value = false;
  } catch (cause) {
    pinError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    pin.value = "";
  }
}

async function confirm(): Promise<void> {
  if (!canConfirm.value) return;

  // BR-044 — a drawer that has been counted takes no more money (D-055). Said
  // on the press, not before it, so the screen carries no standing warning.
  if (!session.canSell) {
    shiftNotice.value = t("home.shiftRequired");
    return;
  }

  if (needsApproval.value && !overrideToken.value) {
    askingPin.value = true;
    return;
  }

  busy.value = true;
  failure.value = null;

  try {
    // D-073 — offline the whole bill goes into the queue as one entry and
    // lands, once, when the connection returns. Nothing is sent now, so there
    // is no invoice number to show; the amount and the change are real.
    if (offline.value) {
      const total = due.value;
      const change = Math.max(round(tendered.value - total), 0);

      if (await orders.payOffline(payable.value.map((line) => ({ ...line })))) {
        done.value = {
          order_name: orderName,
          sales_invoice: "",
          total_amount: total,
          change_amount: change,
        } as paymentApi.PaymentResult;
      } else {
        failure.value = orders.error;
      }
      return;
    }

    done.value = await paymentApi.processPayment({
      order_name: orderName,
      payments: payable.value,
      discount_type: discountType.value,
      discount_value: discountValue.value,
      manager_override_token: overrideToken.value,
    });
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex h-full min-h-0 flex-col">
    <header class="flex items-center gap-3 border-b border-line bg-surface px-4 py-3">
      <RouterLink
        :to="{ name: 'order', params: { orderName } }"
        class="rpos-tap inline-flex items-center px-2 text-primary"
      >
        ←
      </RouterLink>
      <h1 class="font-semibold">
        {{ t("pay.title") }}
      </h1>
      <span class="rpos-numeric text-xs text-muted">{{ orderName }}</span>
    </header>

    <p
      v-if="shiftNotice && !done"
      role="alert"
      class="m-3 mb-0 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
    >
      {{ shiftNotice }}
    </p>

    <!-- Paid: the receipt state, with no way back into an invoiced order. -->
    <section
      v-if="done"
      class="m-auto max-w-sm rounded-rpos bg-surface p-8 text-center shadow-sm"
    >
      <p class="mb-2 text-lg font-semibold text-status-available">
        {{ t("pay.paid") }}
      </p>
      <p class="rpos-numeric mb-1 text-3xl font-bold">
        {{ money(done.total_amount) }}
      </p>
      <p
        v-if="done.change_amount > 0"
        class="rpos-numeric mb-4 text-lg text-status-reserved"
      >
        {{ t("pay.change") }}: {{ money(done.change_amount) }}
      </p>
      <!-- Offline there is no invoice number yet, and saying so is the point:
           the money is taken, the document is not written (D-073). -->
      <p
        v-if="done.sales_invoice"
        class="rpos-numeric mb-6 text-sm text-muted"
      >
        {{ done.sales_invoice }}
      </p>
      <p
        v-else
        class="mb-6 text-sm text-status-cleaning"
      >
        {{ t("offline.paid") }}
      </p>

      <!--
        Straight into the next order (D-055). This used to be one button back to
        a till screen that no longer exists, which put the change on screen and
        then made the cashier find their way to the start again — with a queue
        waiting. `?pane=new` lands on the order types; the second button is for
        the cashier who wants to look at the floor first.
      -->
      <div class="flex flex-col gap-2">
        <button
          type="button"
          class="min-h-tap w-full rounded-rpos bg-primary px-4 font-bold text-primary-contrast"
          @click="router.push({ name: 'home', query: { pane: 'new' } })"
        >
          {{ t("pay.newOrder") }}
        </button>
        <button
          type="button"
          class="min-h-tap w-full rounded-rpos border border-line px-4 font-medium"
          @click="router.push({ name: 'home' })"
        >
          {{ t("nav.orders") }}
        </button>
      </div>
    </section>

    <p
      v-else-if="loadFailure"
      role="alert"
      class="m-4 rounded-rpos bg-danger/10 p-4 text-danger"
    >
      {{ loadFailure }}
    </p>

    <div
      v-else-if="summary"
      class="grid flex-1 gap-3 overflow-y-auto p-3 lg:grid-cols-3"
    >
      <!-- Something the cashier can fix, said **above** the screen and not
           instead of it: the amounts they typed are what they need in order to
           fix it (`D-123`). -->
      <p
        v-if="failure"
        role="alert"
        class="rounded-rpos bg-danger/10 px-3 py-2 text-sm text-danger lg:col-span-3"
      >
        {{ failure }}
      </p>

      <!-- 1 — methods -->
      <section class="rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.methods") }}
        </h2>

        <p
          v-if="forcedMethod"
          class="mb-3 rounded-rpos bg-status-reserved/10 p-2 text-xs text-status-reserved"
        >
          {{ t("pay.forcedMethod", { method: forcedMethod ?? "" }) }}
        </p>

        <div class="mb-3 flex flex-wrap items-center gap-2">
          <span class="text-sm text-muted">{{ t("pay.split") }}</span>
          <button
            v-for="ways in SPLIT_WAYS"
            :key="ways"
            type="button"
            class="min-h-tap min-w-tap rounded-rpos border border-line px-3 text-sm"
            :class="{ 'border-accent font-bold': shares.length === ways }"
            @click="splitInto(ways)"
          >
            {{ ways }}
          </button>
          <button
            v-if="shares.length"
            type="button"
            class="min-h-tap px-2 text-xs text-danger"
            @click="clearSplit"
          >
            {{ t("pay.splitClear") }}
          </button>
        </div>

        <p
          v-if="shares.length"
          class="mb-3 rounded-rpos bg-surface px-3 py-2 text-sm"
        >
          {{
            splitting
              ? t("pay.splitProgress", {
                done: settled,
                ways: shares.length,
                amount: money(shares[settled]),
              })
              : t("pay.splitSettled", { ways: shares.length })
          }}
        </p>

        <!-- Why the buttons went quiet. Without it a dimmed row of methods
             reads as a broken screen rather than a bill that is covered. -->
        <p
          v-if="!canTakeMore && lines.length"
          class="mb-3 text-sm text-muted"
        >
          {{ t("pay.covered") }}
        </p>

        <div class="mb-4 flex flex-wrap gap-2">
          <button
            v-for="method in summary.payment_methods"
            :key="method.payment_method"
            type="button"
            class="min-h-tap rounded-rpos border border-line px-4 text-sm disabled:opacity-40"
            :disabled="!canTakeMore"
            @click="tendering = method"
          >
            {{ method.payment_method }}
          </button>
        </div>

        <!-- What has been taken so far. Read-only: the amount was chosen on the
             sheet, and a field to correct it here is the form that produced a
             tender worth nothing (`D-123`). To change one, remove it and take
             it again — which is one tap more and no wrong states. -->
        <div
          v-for="(line, index) in lines"
          :key="line.method"
          class="mb-2 flex items-baseline gap-2 rounded-rpos bg-background px-3 py-2"
        >
          <span class="flex-1 truncate font-medium">{{ line.method }}</span>
          <span class="rpos-numeric font-bold">{{ money(line.amount) }}</span>
          <!-- Only worth saying when more was handed over than the bill asked
               for, because that is where the change comes from. -->
          <span
            v-if="(line.tendered ?? line.amount) > line.amount + 0.005"
            class="rpos-numeric text-xs text-muted"
          >({{ money(line.tendered ?? 0) }})</span>
          <button
            type="button"
            class="text-xs text-danger"
            @click="removeMethod(index)"
          >
            {{ t("action.remove") }}
          </button>
        </div>
      </section>

      <!-- 2 — discounts -->
      <section class="rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.discounts") }}
        </h2>

        <div class="mb-4 flex gap-2">
          <button
            v-for="percentage in QUICK_DISCOUNTS"
            :key="percentage"
            type="button"
            class="min-h-tap flex-1 rounded-rpos border text-sm"
            :class="
              discountType === 'percentage' && discountValue === percentage
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line'
            "
            @click="setQuickDiscount(percentage)"
          >
            {{ percentage }}%
          </button>
        </div>

        <label
          for="manual-discount"
          class="mb-1 block text-sm font-medium"
        >{{ t("pay.manualDiscount") }}</label>
        <div class="flex gap-2">
          <input
            id="manual-discount"
            v-model.number="discountValue"
            type="number"
            min="0"
            step="0.5"
            class="rpos-numeric min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          >
          <select
            v-model="discountType"
            :aria-label="t('pay.discountType')"
            class="min-h-tap rounded-rpos border border-line bg-background px-2"
          >
            <option :value="null">
              —
            </option>
            <option value="percentage">
              %
            </option>
            <option value="amount">
              {{ t("currency.sar") }}
            </option>
          </select>
        </div>

        <p
          v-if="needsApproval"
          class="mt-3 rounded-rpos bg-status-reserved/10 p-2 text-xs text-status-reserved"
        >
          {{ t("pay.exceedsLimit", { limit: `${preview?.max_discount_percentage ?? 0}%` }) }}
          <span
            v-if="overrideToken"
            class="font-medium text-status-available"
          >{{ t("pay.authorized") }} ✓</span>
        </p>

        <p class="mt-4 text-xs text-muted">
          {{ t("pay.loyaltySoon") }}
        </p>
      </section>

      <!-- 3 — summary -->
      <section class="flex flex-col rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.summary") }}
        </h2>

        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt>{{ t("totals.subtotal") }}</dt>
            <dd class="rpos-numeric">
              {{ money(preview?.subtotal ?? summary.subtotal) }}
            </dd>
          </div>
          <div
            v-if="(preview?.discount_amount ?? summary.discount_amount) > 0"
            class="flex justify-between text-status-available"
          >
            <dt>{{ t("totals.discount") }}</dt>
            <dd class="rpos-numeric">
              −{{ money(preview?.discount_amount ?? summary.discount_amount) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt>{{ t("totals.tax") }}</dt>
            <dd class="rpos-numeric">
              {{ money(preview?.tax_amount ?? summary.tax_amount) }}
            </dd>
          </div>
          <div class="flex justify-between border-t border-line pt-2 text-lg font-bold">
            <dt>{{ t("totals.total") }}</dt>
            <dd class="rpos-numeric">
              {{ money(due) }}
            </dd>
          </div>
        </dl>

        <div class="mt-4 space-y-1 text-sm">
          <div
            v-if="remaining > 0"
            class="flex justify-between text-status-reserved"
          >
            <span>{{ t("pay.remaining") }}</span>
            <span class="rpos-numeric">{{ money(remaining) }}</span>
          </div>
          <div
            v-if="change > 0"
            class="flex justify-between text-lg font-semibold"
          >
            <span>{{ t("pay.change") }}</span>
            <span class="rpos-numeric">{{ money(change) }}</span>
          </div>
        </div>

        <button
          type="button"
          class="mt-auto min-h-tap w-full rounded-rpos bg-primary px-4 text-base font-medium text-primary-contrast disabled:opacity-50"
          :disabled="!canConfirm"
          @click="confirm"
        >
          {{ busy ? "…" : `✅ ${t("pay.confirm")}` }}
        </button>
      </section>
    </div>

    <!--
      The fourth branch, and the reason it exists: without it this screen drew
      its header and then nothing whenever the summary had not arrived — which
      reads as a broken app, not as a screen still loading. A blank page is the
      one thing a till must never show (`D-074`).
    -->
    <p
      v-else
      class="m-4 text-center text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <!-- Screen 9 — manager authorisation -->
    <TenderSheet
      :method="tendering?.payment_method ?? null"
      :due="nextDue"
      :is-cash="Boolean(tendering?.is_cash)"
      @pick="takeTender"
      @close="tendering = null"
    />

    <BaseDialog
      :open="askingPin"
      :title="`🔐 ${t('pay.needsManager')}`"
      @close="askingPin = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("pay.discountExceeds", { value: `${preview?.discount_percentage ?? 0}%` }) }}
      </p>
      <label
        for="pin"
        class="mb-1 block text-sm font-medium"
      >{{ t("pay.managerPin") }}</label>
      <input
        id="pin"
        v-model="pin"
        type="password"
        inputmode="numeric"
        maxlength="4"
        autocomplete="off"
        class="rpos-numeric mb-3 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-center text-2xl tracking-widest"
      >
      <label
        for="pin-reason"
        class="mb-1 block text-sm font-medium"
      >{{ t("pay.reasonRequired") }}</label>
      <input
        id="pin-reason"
        v-model="pinReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
      >
      <p
        v-if="pinError"
        role="alert"
        class="mb-3 text-sm text-danger"
      >
        {{ pinError }}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="askingPin = false"
        >
          {{ t("action.cancel") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
          :disabled="pin.length !== 4 || !pinReason.trim()"
          @click="approveDiscount"
        >
          {{ t("action.authorize") }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
