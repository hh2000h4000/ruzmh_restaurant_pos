<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { reductionsOn } from "@/api/order";
import * as paymentApi from "@/api/payment";
import type {
  PaymentLine,
  PaymentMethodOption,
  PaymentSummary,
  TotalsPreview,
} from "@/api/payment";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import ManagerPinDialog from "@/components/ManagerPinDialog.vue";
import CouponDialog from "@/components/order/CouponDialog.vue";
import GiftCardPayDialog from "@/components/order/GiftCardPayDialog.vue";
import TenderSheet from "@/components/order/TenderSheet.vue";
import { formatNumber, methodName, pick, t } from "@/i18n";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";

/**
 * Screen 6 — payment, **inside the order screen** (`D-386`).
 *
 * It was a page of its own: Pay put the bill away and drew a «summary» of it
 * with no dishes on it. Now it is the working column, the way the orders list
 * and the floor are, and the bill stays where it was — as on Foodics.
 *
 * Top to bottom, the order the work happens in: the methods, each tapped once
 * (a card or an app takes what is owed on the spot; cash asks how much was
 * handed over); what has been taken, with what is left or the change; and Pay.
 * Everything that changes the price — offers, a coupon, a discount, points, an
 * even split — is behind «…», because most bills have none of it.
 *
 * Every figure comes from the server: the discount is previewed by
 * `preview_totals` before the customer is quoted, and the final amount is the
 * one the invoice carries (D-018).
 */
const QUICK_DISCOUNTS = [10, 25, 50];

//: Party sizes a table actually asks to split between. Beyond six the guests
//: are usually paying by item, which is a different feature.
const SPLIT_WAYS = [2, 3, 4, 5, 6];

const props = defineProps<{ orderName: string }>();

const emit = defineEmits<{
  /** Back to the menu, the bill unchanged. */
  back: [];
  /** Paid — straight into the next order. */
  next: [];
  /** Paid — to the list of orders instead. */
  list: [];
}>();

const session = useSessionStore();
const orders = useOrderStore();

const orderName = props.orderName;

/** The sheet behind «…»: offers, coupon, discount, points, split. */
const extrasOpen = ref(false);

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

function isForbidden(method: PaymentMethodOption): boolean {
  return forcedMethods.value.length > 0 && !forcedMethods.value.includes(method.payment_method);
}

/**
 * The methods this bill may be paid with, **and only those** (`D-386`): a
 * HungerStation order shows HungerStation's, not ten buttons eight of which
 * are grey. A method the settlement rule closes stays, greyed, because it
 * opens again when the tender that closed it comes off.
 */
const shownMethods = computed(() =>
  (summary.value?.payment_methods ?? []).filter((method) => !isForbidden(method)),
);

/** Whether a reduction is on the bill, so «…» says so. */
const reduced = computed(
  () =>
    Boolean(discountType.value && discountValue.value) ||
    Boolean(chosenPromotion.value) ||
    loyaltyPoints.value > 0 ||
    Boolean(summary.value?.coupon),
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

/**
 * A bill an offer took to zero — a free coffee and nothing else — closes with no
 * tender at all. It used to need a payment row, and none could be added to a
 * bill with nothing left on it, so the cashier was stuck. The server posts it
 * as a zero invoice (`_assert_tendered`). Read only once the bill has loaded:
 * a zero `due` before then is "not known yet", not "free".
 */
const nothingToPay = computed(() => Boolean(summary.value) && due.value <= 0.005);

const canConfirm = computed(
  () =>
    !busy.value &&
    !blocked.value &&
    (payable.value.length > 0 || nothingToPay.value) &&
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

watch(
  () => orders.order?.total_amount,
  (now, before) => {
    if (offline.value || done.value || now === before || before === undefined) return;
    lines.value = [];
    clearSplit();
    void refresh();
  },
);

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

/**
 * `D-256` — the card a gift-card tender will come off, and the method waiting
 * for it. A card is the one method whose limit the cashier cannot see, so it is
 * looked up before the amount is taken rather than refused afterwards.
 */
const askingForCard = ref<PaymentMethodOption | null>(null);
const heldCard = ref<{ number: string; balance: number } | null>(null);

/** What this tender may be, which for a card is capped by what is on it. */
const tenderCeiling = computed(() =>
  heldCard.value ? Math.min(nextDue.value, heldCard.value.balance) : nextDue.value,
);

function chooseMethod(method: PaymentMethodOption): void {
  if (method.is_gift_card) {
    askingForCard.value = method;
    return;
  }

  tendering.value = method;
  // `D-386` — a card or an app is never handed more than the bill, so one tap
  // takes what is owed, as on Foodics; Pay is the second tap, and a mistaken
  // tender comes off with its ✕. Only cash asks how much was handed over.
  if (!method.is_cash) takeTender(nextDue.value);
}

function cardChosen(card: { number: string; balance: number }): void {
  heldCard.value = card;
  tendering.value = askingForCard.value;
  askingForCard.value = null;
}

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

  const amount = round(Math.min(chosen, tenderCeiling.value));
  const tendered = method.is_cash ? chosen : amount;

  const card = heldCard.value;
  // **Two cards on one bill are two lines.** Every other method merges — four
  // people paying cash are one cash line — but a gift-card line names the card
  // it comes off, and merging them would spend one number for both.
  const existing = card
    ? undefined
    : lines.value.find((line) => line.method === method.payment_method);
  if (existing) {
    // Four people paying cash are one cash line: the invoice records what the
    // drawer holds, not who handed over which note. Without this a split would
    // need the same method four times, and the till would reconcile against
    // rows that mean nothing.
    existing.amount = round(existing.amount + amount);
    existing.tendered = round((existing.tendered ?? existing.amount) + tendered);
  } else {
    lines.value.push({
      method: method.payment_method,
      amount,
      tendered,
      ...(card ? { gift_card: card.number } : {}),
    });
  }

  heldCard.value = null;

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
    shiftNotice.value = session.disabled ? t("home.terminalDisabledHint") : t("home.shiftRequired");
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
  <section class="flex min-h-0 flex-col gap-3">
    <header class="flex shrink-0 items-center gap-3">
      <button
        type="button"
        class="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-surface text-lg"
        :aria-label="t('action.back')"
        @click="emit('back')"
      >
        <span class="rpos-flip">←</span>
      </button>
      <h1 class="text-xl font-medium">
        {{ t("pay.title") }}
      </h1>
    </header>

    <p
      v-if="shiftNotice && !done"
      role="alert"
      class="rounded bg-status-reserved/10 p-3 text-sm text-status-reserved"
    >
      {{ shiftNotice }}
    </p>

    <!-- Paid: the change, read across the counter, and straight on. -->
    <section
      v-if="done"
      class="m-auto w-full max-w-sm rounded-xl bg-surface p-8 text-center"
    >
      <p class="mb-2 text-lg font-semibold text-status-available">
        {{ t("pay.paid") }}
      </p>
      <p class="rpos-numeric mb-1 text-3xl font-semibold">
        {{ money(done.total_amount) }}
      </p>
      <p
        v-if="done.change_amount > 0"
        class="rpos-numeric mb-4 rounded-lg bg-status-available/10 p-3 text-2xl font-semibold text-status-available"
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

      <div class="flex flex-col gap-2">
        <button
          type="button"
          class="min-h-14 w-full rounded-lg bg-primary px-4 font-semibold text-primary-contrast"
          @click="emit('next')"
        >
          {{ t("pay.newOrder") }}
        </button>
        <button
          type="button"
          class="min-h-tap w-full rounded-lg px-4 font-medium text-subtle"
          @click="emit('list')"
        >
          {{ t("nav.orders") }}
        </button>
      </div>
    </section>

    <p
      v-else-if="loadFailure"
      role="alert"
      class="rounded bg-danger/10 p-4 text-danger"
    >
      {{ loadFailure }}
    </p>

    <template v-else-if="summary">
      <!-- Something the cashier can fix, said **above** the screen and not
           instead of it: the amounts they took are what they need to fix it
           (`D-123`). -->
      <p
        v-if="failure"
        role="alert"
        class="rounded bg-danger/10 px-4 py-3 text-sm text-danger"
      >
        {{ failure }}
      </p>
      <p
        v-if="blocker"
        role="alert"
        class="rounded bg-danger/10 px-3 py-2 text-sm text-danger"
      >
        {{ blocker }}
      </p>

      <!-- The methods, white on the screen's grey, scrolling inside themselves
           so Pay never leaves the screen (`D-124`). Each says what tapping it
           takes; cash asks. -->
      <div class="min-h-0 flex-1 overflow-y-auto">
        <div class="grid grid-cols-2 gap-3 xl:grid-cols-3">
          <button
            v-for="method in shownMethods"
            :key="method.payment_method"
            type="button"
            class="flex min-h-[5.5rem] flex-col items-start justify-center gap-1 rounded-lg bg-surface px-4 text-start transition duration-100 ease-rpos active:bg-primary/10 disabled:opacity-40"
            :disabled="blocked || !canTakeMore || mixesSettlement(method)"
            @click="chooseMethod(method)"
          >
            <span class="text-lg font-semibold">{{ methodName(method.payment_method) }}</span>
          </button>
        </div>

        <p
          v-if="!canTakeMore && lines.length"
          class="mt-3 text-sm text-subtle"
        >
          {{ t("pay.covered") }}
        </p>
        <!-- Why half the list went quiet (`D-029`). -->
        <p
          v-else-if="settlementKind"
          class="mt-3 text-sm text-subtle"
        >
          {{ settlementKind === "credit" ? t("pay.creditOnly") : t("pay.tillOnly") }}
        </p>
      </div>

      <!-- What is owed, what has been taken and what is left. -->
      <div class="shrink-0 rounded-xl bg-surface px-5 py-4">
        <div class="flex items-baseline justify-between gap-3">
          <span class="text-sm text-subtle">{{ t("totals.total") }}</span>
          <span class="rpos-numeric text-lg font-medium">{{ money(due) }}</span>
        </div>
        <!-- A reduction chosen behind «…», said where the figure it changed is. -->
        <p
          v-for="row in [
            reductions.promotion ? { label: reductions.promotion.title, amount: reductions.promotion.amount } : null,
            reductions.loyalty ? { label: t('totals.loyalty'), amount: reductions.loyalty.amount } : null,
            reductions.discount > 0 ? { label: t('totals.discount'), amount: reductions.discount } : null,
          ].filter(Boolean)"
          :key="row!.label"
          class="flex justify-between gap-3 text-sm text-secondary"
        >
          <span class="truncate">{{ row!.label }}</span>
          <span class="rpos-numeric shrink-0">−{{ money(row!.amount) }}</span>
        </p>

        <div
          v-for="(line, index) in lines"
          :key="line.method + index"
          class="mt-2 flex items-center gap-2 text-sm"
        >
          <span class="flex-1 truncate">{{ methodName(line.method) }}</span>
          <span class="rpos-numeric">{{ money(line.amount) }}</span>
          <!-- Only worth saying when more was handed over than the bill asked
               for, because that is where the change comes from. -->
          <span
            v-if="(line.tendered ?? line.amount) > line.amount + 0.005"
            class="rpos-numeric text-xs text-muted"
          >({{ money(line.tendered ?? 0) }})</span>
          <button
            type="button"
            class="grid h-9 w-9 min-h-0 place-items-center rounded-full text-muted hover:bg-danger/10 hover:text-danger"
            :aria-label="t('action.remove')"
            @click="removeMethod(index)"
          >
            <AppIcon
              name="close"
              :size="16"
            />
          </button>
        </div>

        <p
          v-if="shares.length"
          class="mt-2 text-sm text-subtle"
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

        <div
          v-if="remaining > 0"
          class="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-3"
        >
          <span class="font-medium">{{ t("pay.remaining") }}</span>
          <span class="rpos-numeric text-2xl font-semibold text-accent-gold">{{ money(remaining) }}</span>
        </div>
        <div
          v-else-if="change > 0"
          class="mt-3 flex items-baseline justify-between gap-3 border-t border-line pt-3"
        >
          <span class="font-medium">{{ t("pay.change") }}</span>
          <span class="rpos-numeric text-2xl font-semibold text-status-available">{{ money(change) }}</span>
        </div>
      </div>

      <!-- Pay, and «…» beside it for everything that changes the price. -->
      <div
        data-pay-bar
        class="flex shrink-0 gap-3"
      >
        <button
          type="button"
          data-extras-open
          class="relative grid h-16 w-16 shrink-0 place-items-center rounded-lg bg-surface text-2xl"
          :aria-label="t('pay.discounts')"
          @click="extrasOpen = true"
        >
          <AppIcon
            name="moreHorizontal"
            :size="26"
            class="text-secondary"
          />
          <span
            v-if="reduced"
            class="absolute end-2 top-2 h-2.5 w-2.5 rounded-full bg-secondary"
          />
        </button>
        <button
          type="button"
          class="min-h-16 flex-1 rounded-lg bg-primary px-4 text-lg font-semibold text-primary-contrast shadow-primary transition duration-200 ease-rpos hover:brightness-110 disabled:opacity-50 disabled:shadow-none"
          :disabled="!canConfirm"
          @click="confirm"
        >
          {{ busy ? "…" : t("pay.confirm") }}
        </button>
      </div>
    </template>

    <!-- `D-074` — never a blank column while the bill is on its way. -->
    <p
      v-else
      class="m-4 text-center text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <!-- «…»: everything that changes the price, one sheet (`D-386`). -->
    <BaseDialog
      :open="extrasOpen"
      :title="t('pay.discounts')"
      pad
      wide
      @close="extrasOpen = false"
    >
      <div
        data-extras
        class="flex flex-col gap-4 pt-2"
      >
        <!-- **What this bill qualifies for** (`D-165`). Above the discount: an
             offer the shop already advertised is the cheaper answer. -->
        <div
          v-if="offers.length"
          class="flex flex-col gap-2"
        >
          <p class="text-sm text-subtle">
            {{ t("pay.promotions") }}
          </p>
          <button
            v-for="offer in offers"
            :key="offer.name"
            type="button"
            :disabled="!mayChoosePromotion"
            class="flex min-h-14 items-center justify-between gap-3 rounded px-4 text-start disabled:cursor-not-allowed disabled:opacity-50"
            :class="chosenPromotion === offer.name ? 'bg-primary text-primary-contrast' : 'bg-surface'"
            :aria-pressed="chosenPromotion === offer.name"
            @click="choosePromotion(offer.name)"
          >
            <span class="min-w-0 truncate text-sm">{{ pick(offer.title_ar, offer.title) }}</span>
            <span class="rpos-numeric shrink-0 text-sm">−{{ money(offer.benefit) }}</span>
          </button>
          <p
            v-if="!mayChoosePromotion"
            class="text-xs text-subtle"
          >
            {{ t("pay.promotionNeedsRight") }}
          </p>
        </div>

        <!-- `D-248` — the guest often produces the code here. -->
        <button
          type="button"
          class="flex min-h-14 items-center justify-between gap-3 rounded bg-surface px-4 text-start text-sm"
          @click="enteringCoupon = true"
        >
          <span class="flex min-w-0 items-center gap-2">
            <AppIcon name="tag" />
            <span class="truncate">{{ summary?.coupon ? summary.coupon.code : t("coupon.add") }}</span>
          </span>
          <span
            v-if="summary?.coupon?.campaign"
            class="shrink-0 truncate text-xs text-subtle"
          >{{ summary.coupon.campaign }}</span>
        </button>

        <div class="grid grid-cols-3 gap-2">
          <button
            v-for="percentage in QUICK_DISCOUNTS"
            :key="percentage"
            type="button"
            class="rpos-numeric min-h-14 rounded text-lg"
            :class="
              discountType === 'percentage' && discountValue === percentage
                ? 'bg-primary text-primary-contrast'
                : 'bg-surface'
            "
            @click="setQuickDiscount(percentage)"
          >
            {{ percentage }}%
          </button>
        </div>

        <div class="flex flex-col gap-2">
          <label
            for="manual-discount"
            class="text-sm text-subtle"
          >{{ t("pay.manualDiscount") }}</label>
          <div class="grid grid-cols-[minmax(0,1fr)_6rem] gap-2">
            <input
              id="manual-discount"
              v-model.number="discountValue"
              type="number"
              min="0"
              step="0.5"
              class="rpos-numeric rpos-field min-h-14 w-full rounded px-4 text-base outline-none focus:ring-2 focus:ring-primary/30"
            >
            <select
              v-model="discountType"
              :aria-label="t('pay.discountType')"
              class="rpos-field min-h-14 rounded px-3 outline-none"
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
          class="rounded bg-accent-gold/10 px-3 py-2 text-xs text-accent-gold"
        >
          {{ t("pay.exceedsLimit", { limit: `${preview?.max_discount_percentage ?? 0}%` }) }}
          <span
            v-if="overrideToken"
            class="font-medium text-status-available"
          >{{ t("pay.authorized") }} ✓</span>
        </p>

        <!-- **The customer's own points** (`FR-10.5`, `D-189`). -->
        <div
          v-if="loyalty"
          class="flex flex-col gap-2"
        >
          <p class="text-sm text-subtle">
            {{ t("pay.loyalty") }} ·
            {{ t("pay.loyaltyBalance", { points: formatNumber(loyalty.balance, 0), worth: money(loyalty.worth) }) }}
          </p>
          <button
            v-if="loyalty.max_points > 0"
            type="button"
            data-loyalty
            class="flex min-h-14 items-center justify-between gap-3 rounded px-4 text-start"
            :class="loyaltyPoints ? 'bg-primary text-primary-contrast' : 'bg-surface'"
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
          <p
            v-else
            class="text-xs text-subtle"
          >
            {{
              loyalty.balance < loyalty.min_points
                ? t("pay.loyaltyBelowMinimum", { points: formatNumber(loyalty.min_points, 0) })
                : t("pay.loyaltyNothingFits")
            }}
          </p>
        </div>

        <!-- An even split between the table (`FR-10.3`). -->
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-subtle">{{ t("pay.split") }}</span>
          <button
            v-for="ways in SPLIT_WAYS"
            :key="ways"
            type="button"
            class="rpos-numeric grid h-12 w-12 place-items-center rounded"
            :class="shares.length === ways ? 'bg-primary text-primary-contrast' : 'bg-surface'"
            @click="splitInto(ways)"
          >
            {{ ways }}
          </button>
          <button
            v-if="shares.length"
            type="button"
            class="min-h-12 rounded px-3 text-sm font-medium text-danger"
            @click="clearSplit"
          >
            {{ t("pay.splitClear") }}
          </button>
        </div>

        <button
          type="button"
          class="rpos-pad-done"
          @click="extrasOpen = false"
        >
          {{ t("action.done") }}
        </button>
      </div>
    </BaseDialog>

    <TenderSheet
      :method="tendering?.is_cash || heldCard ? (tendering?.payment_method ?? null) : null"
      :due="tenderCeiling"
      :is-cash="Boolean(tendering?.is_cash)"
      @pick="takeTender"
      @close="
        tendering = null;
        heldCard = null;
      "
    />

    <!-- `D-256` — which card, and what is on it, before any amount is taken. -->
    <GiftCardPayDialog
      :open="Boolean(askingForCard)"
      @found="cardChosen"
      @close="askingForCard = null"
    />

    <CouponDialog
      :open="enteringCoupon"
      :order-name="orders.order?.order_name ?? null"
      :applied="summary?.coupon ?? null"
      @changed="void refresh()"
      @close="enteringCoupon = false"
    />

    <!-- Screen 9 — manager authorisation -->
    <ManagerPinDialog
      :open="askingPin"
      :explain="t('pay.discountExceeds', { value: `${preview?.discount_percentage ?? 0}%` })"
      :verify="approveDiscount"
      @approved="onApproved"
      @close="askingPin = false"
    />
  </section>
</template>
