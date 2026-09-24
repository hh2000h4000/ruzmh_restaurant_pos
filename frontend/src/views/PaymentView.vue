<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { reductionsOn } from "@/api/order";
import * as paymentApi from "@/api/payment";
import type {
  PaymentLine,
  PaymentMethodOption,
  PaymentSummary,
  TotalsPreview,
} from "@/api/payment";
import AppIcon from "@/components/AppIcon.vue";
import ManagerPinDialog from "@/components/ManagerPinDialog.vue";
import CouponDialog from "@/components/order/CouponDialog.vue";
import TenderSheet from "@/components/order/TenderSheet.vue";
import { formatNumber, pick, t } from "@/i18n";
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
const enteringCoupon = ref(false);
const preview = ref<TotalsPreview | null>(null);
const lines = ref<PaymentLine[]>([]);

//: The shares of an even split, and how many have been handed over. Computed
//: on the server (`CLAUDE.md` §5.1) — the last five halalas of 100.00 between
//: three are the whole difficulty.
const shares = ref<number[]>([]);
const settled = ref(0);
const discountType = ref<"percentage" | "amount" | null>(null);
const discountValue = ref(0);

/**
 * The promotion the cashier picked, and what there is to pick from (`D-165`).
 *
 * A promotion with `is_auto_apply` off is **offered**, not taken — and the
 * engine shipped with nothing to offer it on: it could be configured, saved and
 * listed as active while no screen showed it and nothing applied it.
 *
 * `mayChoosePromotion` comes from the server with the list, so the choice can be
 * greyed rather than refused after the customer has been told a price (`D-125`).
 * The server checks it again regardless (§5.4).
 */
const chosenPromotion = ref<string | null>(null);
const offers = ref<paymentApi.PromotionOffer[]>([]);
const mayChoosePromotion = ref(false);

/**
 * Points the customer is spending on this bill (`FR-10.5`, `D-189`).
 *
 * The third way to reduce a bill, and it takes the same road as the other two:
 * previewed by `preview_totals`, sent with the payment, checked again by the
 * server against the balance under a lock. The offer — balance, minimum, the
 * most this bill can take — comes from the server with the figures, so the
 * button offers exactly what will be accepted (`D-125`).
 */
const loyaltyPoints = ref(0);
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

const due = computed(() => preview.value?.total_amount ?? summary.value?.total_amount ?? 0);
const paid = computed(() => lines.value.reduce((total, line) => total + (line.amount || 0), 0));
const remaining = computed(() => round(due.value - paid.value));
const tendered = computed(() =>
  lines.value.reduce((total, line) => total + (line.tendered ?? line.amount ?? 0), 0),
);
const change = computed(() => (remaining.value <= 0 ? round(tendered.value - due.value) : 0));

/** True while a share is still waiting to be handed over. */
const splitting = computed(() => settled.value < shares.value.length);

/**
 * `BR-023` — the methods an order type *forces*, when it forces any.
 *
 * An app order is settled by the app, and taking cash for one puts money in the
 * till that the platform also pays out. The server has always refused it; it
 * refused it at Confirm, while this screen showed a sentence above a list of
 * live buttons — so a cashier could tap Cash on a delivery order, count out the
 * change, and only then be told (`D-125`). A rule about which buttons may be
 * used belongs on the buttons.
 *
 * A list rather than the first row, matching `_validate_methods` exactly: a
 * type that forces two methods accepts either, and disabling the second here
 * would forbid what the shop allows.
 */
const forcedMethods = computed(() =>
  (summary.value?.payment_methods ?? [])
    .filter((method) => method.is_forced)
    .map((method) => method.payment_method),
);

/** The one named in the hint — the same row the server's message names. */
const forcedMethod = computed(() => forcedMethods.value[0] ?? null);

function isForbidden(method: PaymentMethodOption): boolean {
  return forcedMethods.value.length > 0 && !forcedMethods.value.includes(method.payment_method);
}
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

/**
 * Which way this bill is being settled once the first tender is taken.
 *
 * `D-029` — an order is **settled at the till or billed to an account, never
 * both**: half to a delivery platform and half in cash leaves a
 * partly-outstanding invoice inside a cash-drawer reconciliation. The server
 * has always refused the mix; it refused it at Confirm, after two tenders had
 * been taken and the customer had been told a total. It is a rule about which
 * *buttons* are available, so it belongs on the buttons (`D-125`).
 */
const settlementKind = computed<"credit" | "till" | null>(() => {
  const first = lines.value[0];
  if (!first) return null;

  const method = summary.value?.payment_methods.find(
    (row) => row.payment_method === first.method,
  );
  return method?.is_credit ? "credit" : "till";
});

function mixesSettlement(method: PaymentMethodOption): boolean {
  if (!settlementKind.value) return false;
  return (method.is_credit ? "credit" : "till") !== settlementKind.value;
}

/**
 * A setup fault that stops the sale before it starts (`D-125`).
 *
 * The server reports it when the screen opens instead of throwing it out of the
 * Sales Invoice at Confirm. There is nothing the cashier can do about it at the
 * till, so the methods go quiet and the sentence names the document a manager
 * has to fix.
 */
const blocker = computed(() => summary.value?.blocker ?? null);

/**
 * Nothing can be tendered on this bill at all — a setup fault, or an order that
 * already has an invoice (`BR-016`).
 *
 * The already-paid case put its sentence on the screen and then left every
 * button live, so a cashier could compose a whole second payment on a bill that
 * was settled and be refused at the end of it. A message the buttons contradict
 * is a message nobody reads (`D-125`).
 */
const blocked = computed(() => Boolean(blocker.value) || Boolean(summary.value?.already_paid));

const canConfirm = computed(
  () =>
    !busy.value &&
    !blocked.value &&
    payable.value.length > 0 &&
    remaining.value <= 0.005 &&
    !done.value,
);
const needsApproval = computed(() => Boolean(preview.value?.requires_override));

/**
 * The two reductions, told apart (`D-163`) — one subtraction, in `api/order`.
 *
 * The preview is the live figure while a discount is being typed and the stored
 * summary is what the bill already holds, so both sources are read the same way
 * here as everywhere else on this screen.
 *
 * **The manager approving a discount must be shown the discount**, not the
 * discount plus an offer that was applied before anybody asked. Reading one
 * folded figure is how an approval that was never needed gets requested, and how
 * one that was needed does not.
 */
const reductions = computed(() =>
  reductionsOn(
    preview.value ?? (summary.value ? { ...summary.value } : null),
  ),
);

/**
 * What this customer's points can do on the bill as it now stands, or `null`
 * when the bill is outside the scheme — and then the column says nothing.
 *
 * The preview's when there is one, because the most a bill can take is a share
 * of what is left after the discount and the offer the cashier is choosing.
 */
const loyalty = computed(() => (preview.value ?? summary.value)?.loyalty ?? null);

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
      // **No promotion offline** — the engine reads the promotion table and the
      // clock on the server (`D-163`). Carried through as none rather than left
      // out, so this screen shows the same bill the till showed.
      promotion_amount: bill.promotion_amount,
      promotion_title: bill.promotion_title,
      promotion_title_ar: bill.promotion_title_ar,
      tax_amount: bill.tax_amount,
      total_amount: bill.total_amount,
      already_paid: false,
      sales_invoice: null,
      // Offline the invoice is not written here, so there is nothing to block
      // yet; the replay asks the same question when it reaches the server.
      blocker: null,
      // The terminal's own methods. Which ones an order *type* forbids
      // (`BR-023`) is on the server, so the replay is what enforces it — a
      // device that guessed would refuse a method the shop allows.
      payment_methods: (session.data?.payment_methods ?? []).map((row) => ({
        payment_method: row.mode_of_payment,
        is_forced: 0 as const,
        is_default: row.default,
        is_cash: row.is_cash,
        is_credit: row.is_credit,
      })),
    };
    return;
  }

  await refresh();
});

/**
 * Read the bill and what it is offered, from the server.
 *
 * Split out of `onMounted` so a coupon can re-run it (`D-248`): a code both
 * changes the figures and can bring an offer into the list, so refetching one
 * without the other would leave the screen half true.
 */
async function refresh(): Promise<void> {
  // `orderName` is the route's, set at the top of this file. Reading it off the
  // store instead shadowed it with a value that is null until the bill loads,
  // and the screen sat on "loading" for ever.
  if (offline.value) return;

  try {
    summary.value = await paymentApi.getPaymentSummary(orderName);
    if (summary.value.already_paid) {
      failure.value = t("pay.alreadyPaid", { invoice: summary.value.sales_invoice ?? "" });
    }
  } catch (cause) {
    loadFailure.value = cause instanceof Error ? cause.message : String(cause);
  }

  // **Asked separately, and it must not be able to stop a payment.** What is on
  // offer is worth showing and taking the money is worth more: an offers call
  // that failed inside the block above would leave the screen with no bill at
  // all over a list nobody has to use (`D-165`).
  try {
    const available = await paymentApi.promotionOffers(orderName);
    offers.value = available.offers;
    mayChoosePromotion.value = available.may_choose;
    chosenPromotion.value = available.offers.find((offer) => offer.is_chosen)?.name ?? null;
  } catch {
    // No list, and the automatic promotions still apply themselves.
    offers.value = [];
  }
}

/**
 * What the bill comes to with whatever has been chosen (FR-10.4, `D-165`).
 *
 * One call for both, because they are one question — *reduce this bill* — and
 * the server folds them into one figure anyway. Two calls would let the screen
 * show a total neither of them produced.
 */
async function reprice(): Promise<void> {
  if (
    !discountType.value &&
    !discountValue.value &&
    !chosenPromotion.value &&
    !loyaltyPoints.value
  ) {
    preview.value = null;
    return;
  }

  try {
    preview.value = await paymentApi.previewTotals(
      orderName,
      discountType.value,
      discountValue.value,
      chosenPromotion.value,
      loyaltyPoints.value,
    );
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
}

// **The approval belongs to the discount, so only the discount drops it.** A
// token is bound to a percentage a manager approved; picking a promotion does
// not change that percentage, and dropping it there would send the cashier back
// to the manager for a figure already approved.
watch([discountType, discountValue], () => {
  overrideToken.value = null;
  void reprice();
});

watch(chosenPromotion, () => void reprice());
watch(loyaltyPoints, () => void reprice());

/**
 * A bigger discount leaves less for the points to pay, so the most the bill can
 * take may drop under what was already chosen. Brought down to it rather than
 * left to be refused at Confirm (`D-125`).
 */
watch(
  () => loyalty.value?.max_points,
  (most) => {
    if (loyaltyPoints.value > (most ?? 0)) loyaltyPoints.value = most ?? 0;
  },
);

/** Spend as much as the bill can take, or tap again to spend nothing. */
function toggleLoyalty(): void {
  loyaltyPoints.value = loyaltyPoints.value ? 0 : (loyalty.value?.max_points ?? 0);
}

/**
 * Pick an offer, or tap the chosen one again to drop it.
 *
 * Dropping hands the bill back to the automatic pick rather than to nothing:
 * a promotion the shop advertised and applies by itself is not something a
 * cashier removes by changing their mind about a different one.
 */
function choosePromotion(name: string): void {
  chosenPromotion.value = chosenPromotion.value === name ? null : name;
}

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

/**
 * Exchange the manager's PIN for a token (FR-10.4, BR-031).
 *
 * The sheet that collects it is `ManagerPinDialog`, shared with the return
 * screen (`D-147`); what is particular to a discount is this call — the
 * approver's own ceiling has to cover the figure, which a plain yes/no
 * override does not ask.
 */
async function approveDiscount(pin: string, reason: string): Promise<string> {
  const approval = await paymentApi.validateDiscountOverride({
    pin,
    percentage: preview.value?.discount_percentage ?? 0,
    reason,
    branch: session.branch ?? "",
    pos_profile: session.profile?.name ?? "",
    order_name: orderName,
  });

  return approval.override_token;
}

function onApproved(token: string): void {
  overrideToken.value = token;
  askingPin.value = false;
  void confirm();
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
      promotion: chosenPromotion.value,
      manager_override_token: overrideToken.value,
      loyalty_points_redeemed: loyaltyPoints.value,
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
    <!-- The header sits on the page, not on a bar of its own: three cards on a
         warm ground is the whole composition, and a white strip above them
         adds a fourth surface that means nothing. -->
    <header class="flex shrink-0 items-center gap-4 px-6 pb-4 pt-5">
      <RouterLink
        :to="{ name: 'order', params: { orderName } }"
        class="grid h-10 w-10 shrink-0 place-items-center rounded-rpos border border-line bg-surface text-lg text-content transition duration-200 ease-rpos hover:bg-background"
        :aria-label="t('action.back')"
      >
        <span class="rpos-flip">←</span>
      </RouterLink>
      <h1 class="text-2xl font-medium tracking-tight">
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
      <!-- What the bill earned, said while the guest is still at the counter
           — the moment a loyalty scheme is actually noticed (`D-189`). -->
      <p
        v-if="done.loyalty_points_earned"
        class="mb-4 text-sm text-secondary"
      >
        {{
          t("pay.loyaltyEarned", {
            points: formatNumber(done.loyalty_points_earned, 0),
            balance: formatNumber(done.loyalty_balance ?? 0, 0),
          })
        }}
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

    <!-- Columns in the order the work happens: take the money, adjust the
         price, read the bill out. The widths are the reference's — the methods
         column is the widest because it is the one being worked in, and the
         summary is capped so a long total never squeezes the other two. -->
    <div
      v-else-if="summary"
      class="grid flex-1 gap-5 overflow-y-auto px-6 pb-7 lg:min-h-0 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)_minmax(268px,340px)] lg:overflow-hidden"
    >
      <!-- Something the cashier can fix, said **above** the screen and not
           instead of it: the amounts they typed are what they need in order to
           fix it (`D-123`). -->
      <p
        v-if="failure"
        role="alert"
        class="rounded-rpos-lg bg-danger/10 px-4 py-3 text-sm text-danger lg:col-span-3"
      >
        {{ failure }}
      </p>

      <!-- 1 — methods.
           **The column scrolls, not the screen.** A shop with nine payment
           methods pushed the page down and took the Pay button off the bottom
           of it, which on a till is the one control that must never move
           (`D-124`). Each column keeps its own scrollbar from `lg` up; below
           that the three stack and the page scrolls, which is right on a
           phone. -->
      <section
        class="flex flex-col gap-4 rounded-rpos-lg border border-line bg-surface px-6 py-5 lg:min-h-0"
      >
        <h2 class="text-xs text-muted">
          {{ t("pay.methods") }}
        </h2>

        <!-- Nothing on this bill can be paid until a manager fixes the
             terminal. Said first and in the danger colour, because it is the
             only thing on the column that matters. -->
        <p
          v-if="blocker"
          role="alert"
          class="rounded-rpos bg-danger/10 px-3 py-2 text-sm text-danger"
        >
          {{ blocker }}
        </p>

        <p
          v-if="forcedMethod"
          class="rounded-rpos bg-accent-gold/10 px-3 py-2 text-xs text-accent-gold"
        >
          {{ t("pay.forcedMethod", { method: forcedMethod ?? "" }) }}
        </p>

        <div class="flex flex-wrap items-center gap-2.5">
          <span class="text-sm text-muted">{{ t("pay.split") }}</span>
          <!-- The chosen number fills, it does not merely embolden. A cashier
               taking money at speed does not read font weights, and the old
               `border-accent` was not even a colour: `accent` is a palette of
               named shades with no default, so Tailwind generated nothing and
               the only feedback in the screen was the bold. A filled block is
               visible from arm's length, which is the distance a till is read
               from. -->
          <button
            v-for="ways in SPLIT_WAYS"
            :key="ways"
            type="button"
            class="rpos-numeric grid min-h-tap min-w-tap place-items-center rounded-rpos border px-3 text-base transition duration-200 ease-rpos"
            :class="
              shares.length === ways
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line bg-background text-content hover:border-primary'
            "
            @click="splitInto(ways)"
          >
            {{ ways }}
          </button>
        </div>

        <!-- What the split is doing, and how to stop it — one block, because
             they are one thought. The reference sets the undo as bare text; it
             is a box here because as plain words it read as a caption and was
             tapped by nobody. -->
        <div
          v-if="shares.length || !canTakeMore || settlementKind"
          class="flex flex-col items-start gap-2.5"
        >
          <button
            v-if="shares.length"
            type="button"
            class="min-h-tap rounded-rpos border border-danger px-3 text-sm font-medium text-danger transition duration-200 ease-rpos hover:bg-danger/5"
            @click="clearSplit"
          >
            {{ t("pay.splitClear") }}
          </button>

          <p
            v-if="shares.length"
            class="text-sm leading-relaxed text-muted"
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
            class="text-sm leading-relaxed text-muted"
          >
            {{ t("pay.covered") }}
          </p>

          <!-- Why half the list went quiet. The rule is real and old (`D-029`);
               what is new is saying it before the sale is refused over it. -->
          <p
            v-else-if="settlementKind"
            class="text-sm leading-relaxed text-muted"
          >
            {{ settlementKind === "credit" ? t("pay.creditOnly") : t("pay.tillOnly") }}
          </p>
        </div>

        <!-- A list, not a wrapped grid. Methods are read down a column and
             tapped by name; a grid reflows as the list changes and moves the
             one under the cashier's thumb. -->
        <div class="flex min-h-0 flex-1 flex-col gap-2 lg:overflow-y-auto lg:pe-1">
          <button
            v-for="method in summary.payment_methods"
            :key="method.payment_method"
            type="button"
            class="flex min-h-[3.5rem] w-full shrink-0 items-center rounded-rpos border border-line bg-background px-[18px] text-start font-medium transition duration-200 ease-rpos hover:border-primary disabled:opacity-40 disabled:hover:border-line"
            :disabled="
              blocked ||
                !canTakeMore ||
                isForbidden(method) ||
                mixesSettlement(method)
            "
            @click="tendering = method"
          >
            <!-- A method's name is a brand — Cash, mada, Jahez — and it is
                 written the way it is written, not reordered by the paragraph
                 it sits in. -->
            <span dir="ltr">{{ method.payment_method }}</span>
          </button>
        </div>

        <!-- What has been taken, and what is left — together, at the bottom of
             the column where the work is happening.
             
             **Not written onto the method buttons themselves**, which was the
             obvious idea and is wrong: a button that says "tap to take money"
             cannot also say "this much was taken", and the moment three people
             pay cash it would have to say both about one control. The list is a
             record, the buttons are a menu, and Foodics keeps them apart for
             the same reason. Removing a tender also needs its own control, and
             a button inside a button is a mis-tap waiting on a touch screen.
             
             Read-only: the amount was chosen on the sheet, and a field to
             correct it here is the form that produced a tender worth nothing
             (`D-123`). To change one, remove it and take it again. -->
        <div class="mt-auto shrink-0 border-t border-line pt-4">
          <!-- Each tender, with its own way out. Read-only: the amount was
               chosen on the sheet, and a field to correct it here is the form
               that produced a tender worth nothing (`D-123`). To change one,
               remove it and take it again. -->
          <div
            v-for="(line, index) in lines"
            :key="line.method"
            class="mb-2.5 flex items-baseline gap-2 text-sm"
          >
            <span
              dir="ltr"
              class="flex-1 truncate text-start"
            >{{ line.method }}</span>
            <span class="rpos-numeric">{{ money(line.amount) }}</span>
            <!-- Only worth saying when more was handed over than the bill asked
                 for, because that is where the change comes from. -->
            <span
              v-if="(line.tendered ?? line.amount) > line.amount + 0.005"
              class="rpos-numeric text-xs text-muted"
            >({{ money(line.tendered ?? 0) }})</span>
            <button
              type="button"
              class="min-h-0 text-xs text-danger hover:underline"
              @click="removeMethod(index)"
            >
              {{ t("action.remove") }}
            </button>
          </div>

          <div class="flex items-baseline justify-between gap-3">
            <span class="text-sm text-muted">{{ t("pay.taken") }}</span>
            <span class="rpos-numeric text-base">{{ money(paid) }}</span>
          </div>

          <!-- The one figure the cashier is actually working towards, so it is
               the largest thing in the column and the only coloured one. -->
          <div
            v-if="remaining > 0"
            class="mt-2.5 flex items-baseline justify-between gap-3"
          >
            <span class="text-sm font-medium">{{ t("pay.remaining") }}</span>
            <span class="rpos-numeric text-2xl font-medium text-accent-gold">{{
              money(remaining)
            }}</span>
          </div>
          <div
            v-else-if="change > 0"
            class="mt-2.5 flex items-baseline justify-between gap-3"
          >
            <span class="text-sm font-medium">{{ t("pay.change") }}</span>
            <span class="rpos-numeric text-2xl font-medium">{{ money(change) }}</span>
          </div>
        </div>
      </section>

      <!-- 2 — discounts -->
      <section
        class="flex flex-col content-start gap-4 rounded-rpos-lg border border-line bg-surface px-6 py-5 lg:min-h-0 lg:overflow-y-auto"
      >
        <h2 class="text-xs text-muted">
          {{ t("pay.discounts") }}
        </h2>

        <!-- **What this bill qualifies for** (`D-165`).

             A promotion with `is_auto_apply` off is offered rather than taken,
             and this is where it is offered. Above the discount deliberately:
             an offer the shop already advertised is the cheaper answer, and a
             cashier who reaches for a manual discount first gives away money
             the shop had already decided how to give away.

             Each row carries **what it would take off**, so two offers are
             compared as amounts rather than as names. Tapping the chosen one
             again clears it and hands the bill back to the automatic pick. -->
        <div
          v-if="offers.length"
          class="flex flex-col gap-2.5"
        >
          <p class="text-sm font-medium">
            {{ t("pay.promotions") }}
          </p>
          <button
            v-for="offer in offers"
            :key="offer.name"
            type="button"
            :disabled="!mayChoosePromotion"
            class="flex min-h-[3.375rem] items-center justify-between gap-3 rounded-rpos border px-[18px] text-start transition duration-200 ease-rpos disabled:cursor-not-allowed disabled:opacity-50"
            :class="
              chosenPromotion === offer.name
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line bg-background hover:border-primary'
            "
            :aria-pressed="chosenPromotion === offer.name"
            @click="choosePromotion(offer.name)"
          >
            <span class="min-w-0 truncate text-sm">
              {{ pick(offer.title_ar, offer.title) }}
            </span>
            <span class="rpos-numeric shrink-0 text-sm">−{{ money(offer.benefit) }}</span>
          </button>
          <!-- Said before the choice, not after the refusal (`D-125`). -->
          <p
            v-if="!mayChoosePromotion"
            class="text-xs text-muted"
          >
            {{ t("pay.promotionNeedsRight") }}
          </p>
        </div>

        <!-- `D-248` — the guest often produces the code here rather than while
             ordering, so the same dialog the order screen opens is reachable
             from beside the offers it unlocks. -->
        <button
          type="button"
          class="flex min-h-[3.375rem] items-center justify-between gap-3 rounded-rpos border border-line bg-background px-[18px] text-start text-sm transition duration-200 ease-rpos hover:border-primary"
          @click="enteringCoupon = true"
        >
          <span class="flex min-w-0 items-center gap-2">
            <AppIcon name="tag" />
            <span class="truncate">{{ summary?.coupon ? summary.coupon.code : t("coupon.add") }}</span>
          </span>
          <span
            v-if="summary?.coupon?.campaign"
            class="shrink-0 truncate text-xs text-subtle"
          >
            {{ summary.coupon.campaign }}
          </span>
        </button>

        <!-- Three of equal width, because they are three answers to one
             question and a row of different sizes reads as a hierarchy that
             is not there. -->
        <div class="grid grid-cols-3 gap-2.5">
          <button
            v-for="percentage in QUICK_DISCOUNTS"
            :key="percentage"
            type="button"
            class="rpos-numeric grid min-h-[3.5rem] place-items-center rounded-rpos border text-lg transition duration-200 ease-rpos"
            :class="
              discountType === 'percentage' && discountValue === percentage
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line bg-background hover:border-primary'
            "
            @click="setQuickDiscount(percentage)"
          >
            {{ percentage }}%
          </button>
        </div>

        <div class="flex flex-col gap-2.5">
          <label
            for="manual-discount"
            class="block text-sm font-medium"
          >{{ t("pay.manualDiscount") }}</label>
          <div class="grid grid-cols-[minmax(0,1fr)_6rem] gap-2.5">
            <input
              id="manual-discount"
              v-model.number="discountValue"
              type="number"
              min="0"
              step="0.5"
              class="rpos-numeric min-h-[3.375rem] w-full rounded-rpos border border-line bg-background px-[18px] text-base outline-none transition duration-200 ease-rpos focus:border-primary focus:bg-surface"
            >
            <select
              v-model="discountType"
              :aria-label="t('pay.discountType')"
              class="min-h-[3.375rem] rounded-rpos border border-line bg-background px-4 outline-none transition duration-200 ease-rpos focus:border-primary focus:bg-surface"
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
        </div>

        <p
          v-if="needsApproval"
          class="rounded-rpos bg-accent-gold/10 px-3 py-2 text-xs text-accent-gold"
        >
          {{ t("pay.exceedsLimit", { limit: `${preview?.max_discount_percentage ?? 0}%` }) }}
          <span
            v-if="overrideToken"
            class="font-medium text-status-available"
          >{{ t("pay.authorized") }} ✓</span>
        </p>

        <!-- **The customer's own points** (`FR-10.5`, `D-189`). Last in the
             column because they are spent on what is left once the shop's own
             reductions are taken, and the server works them out in that order.

             One button, for the most this bill can take: the server sends that
             figure and what it is worth, so the screen neither multiplies nor
             offers a number it would refuse. Nothing is drawn when the bill is
             outside the scheme — a hint about points on a walk-in's coffee is
             noise. -->
        <div
          v-if="loyalty"
          class="flex flex-col gap-2.5"
        >
          <p class="text-sm font-medium">
            {{ t("pay.loyalty") }}
          </p>
          <p class="text-sm text-muted">
            {{
              t("pay.loyaltyBalance", {
                points: formatNumber(loyalty.balance, 0),
                worth: money(loyalty.worth),
              })
            }}
          </p>
          <button
            v-if="loyalty.max_points > 0"
            type="button"
            data-loyalty
            class="flex min-h-[3.375rem] items-center justify-between gap-3 rounded-rpos border px-[18px] text-start transition duration-200 ease-rpos"
            :class="
              loyaltyPoints
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line bg-background hover:border-primary'
            "
            :aria-pressed="loyaltyPoints > 0"
            @click="toggleLoyalty"
          >
            <span class="text-sm">
              {{ t("pay.loyaltyUse", { points: formatNumber(loyaltyPoints || loyalty.max_points, 0) }) }}
            </span>
            <span class="rpos-numeric shrink-0 text-sm">−{{
              money(loyaltyPoints ? (preview?.loyalty_amount ?? loyalty.max_amount) : loyalty.max_amount)
            }}</span>
          </button>
          <!-- Why there is no button: said, not left for the cashier to guess. -->
          <p
            v-else
            class="text-xs text-muted"
          >
            {{
              loyalty.balance < loyalty.min_points
                ? t("pay.loyaltyBelowMinimum", { points: formatNumber(loyalty.min_points, 0) })
                : t("pay.loyaltyNothingFits")
            }}
          </p>
        </div>
      </section>

      <!-- 3 — summary -->
      <section
        class="flex flex-col gap-4 rounded-rpos-lg border border-line bg-surface px-6 py-5 lg:min-h-0"
      >
        <h2 class="text-xs text-muted">
          {{ t("pay.summary") }}
        </h2>

        <dl class="flex flex-col gap-3 text-sm">
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-muted">
              {{ t("totals.subtotal") }}
            </dt>
            <dd class="rpos-numeric">
              {{ money(preview?.subtotal ?? summary.subtotal) }}
            </dd>
          </div>
          <!-- The two lines that move the total *down*, so the two that carry a
               colour. `rpos-numeric` isolates them, which is what keeps the
               minus sign on the left of the figure instead of drifting to the
               Arabic end of the row.

               They are two lines rather than one because they are two different
               things (`BR-032`, `D-163`): the promotion is a rule the shop
               configured and nobody here chose, the discount is somebody's
               decision inside their ceiling. This is the screen where a manager
               is asked to approve the second, so it must not be reading the
               first. -->
          <div
            v-if="reductions.promotion"
            class="flex items-baseline justify-between gap-3 text-secondary"
          >
            <dt class="truncate">
              {{ reductions.promotion.title }}
            </dt>
            <dd class="rpos-numeric shrink-0">
              −{{ money(reductions.promotion.amount) }}
            </dd>
          </div>
          <!-- A third line, not folded into the discount: the guest spent their
               own balance, and a manager approving a discount must be shown
               the discount alone (`D-189`). -->
          <div
            v-if="reductions.loyalty"
            class="flex items-baseline justify-between gap-3 text-secondary"
          >
            <dt>{{ t("totals.loyalty") }}</dt>
            <dd class="rpos-numeric">
              −{{ money(reductions.loyalty.amount) }}
            </dd>
          </div>
          <div
            v-if="reductions.discount > 0"
            class="flex items-baseline justify-between gap-3 text-secondary"
          >
            <dt>{{ t("totals.discount") }}</dt>
            <dd class="rpos-numeric">
              −{{ money(reductions.discount) }}
            </dd>
          </div>
          <div class="flex items-baseline justify-between gap-3">
            <dt class="text-muted">
              {{ t("totals.tax") }}
            </dt>
            <dd class="rpos-numeric">
              {{ money(preview?.tax_amount ?? summary.tax_amount) }}
            </dd>
          </div>
        </dl>

        <!-- The figure the customer is told. Set large enough to be read
             across a counter, and given the whole middle of the card so
             nothing competes with it. -->
        <div
          class="flex items-baseline justify-between gap-3 border-t border-line pt-4 lg:flex-1 lg:items-start"
        >
          <span class="text-base font-semibold">{{ t("totals.total") }}</span>
          <span class="rpos-numeric text-[2rem] font-medium leading-none tracking-tighter">{{
            money(due)
          }}</span>
        </div>

        <button
          type="button"
          class="mt-auto min-h-[3.875rem] w-full rounded-rpos-lg bg-primary px-4 text-base font-medium text-primary-contrast shadow-primary transition duration-200 ease-rpos hover:brightness-110 disabled:opacity-50 disabled:shadow-none"
          :disabled="!canConfirm"
          @click="confirm"
        >
          {{ busy ? "…" : t("pay.confirm") }}
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

    <CouponDialog
      :open="enteringCoupon"
      :order-name="orders.order?.order_name ?? null"
      :applied="summary?.coupon ?? null"
      @changed="void refresh()"
      @close="enteringCoupon = false"
    />

    <ManagerPinDialog
      :open="askingPin"
      :explain="t('pay.discountExceeds', { value: `${preview?.discount_percentage ?? 0}%` })"
      :verify="approveDiscount"
      @approved="onApproved"
      @close="askingPin = false"
    />
  </main>
</template>
