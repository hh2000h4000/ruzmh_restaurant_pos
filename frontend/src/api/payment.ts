/**
 * Payment endpoints (07 §3, FR-10.x).
 *
 * `previewTotals` exists because the frontend must never compute money
 * (`CLAUDE.md` §5.1): the discount is applied on the server and the resulting
 * figures come back before anyone is charged.
 */
import type { LoyaltyOnBill, PromotionOnBill } from "./order";
import { command, mutate, query } from "./client";

export interface PaymentMethodOption {
  payment_method: string;
  is_forced: 0 | 1;
  is_default: 0 | 1;
  /** Takes notes, so it can be handed more than the bill and give change. */
  is_cash: 0 | 1;
  /** Leaves the money owed rather than collected — a platform or an account. */
  is_credit: 0 | 1;
}

export interface PaymentSummary extends PromotionOnBill, LoyaltyOnBill {
  order_name: string;
  subtotal: number;
  discount_amount: number;
  tax_amount: number;
  total_amount: number;
  payment_methods: PaymentMethodOption[];
  already_paid: boolean;
  sales_invoice: string | null;
  /**
   * Why this bill cannot be invoiced at all — a terminal missing its default
   * customer, say — or `null` when it can. Already translated by the server,
   * because it names a document the cashier has to go and look at.
   */
  blocker: string | null;
}

export interface TotalsPreview extends PromotionOnBill, LoyaltyOnBill {
  subtotal: number;
  discount_amount: number;
  tax_amount: number;
  total_amount: number;
  discount_percentage: number;
  max_discount_percentage: number;
  /** True when this discount needs a manager PIN (FR-10.4). */
  requires_override: boolean;
}

export interface PaymentLine {
  method: string;
  amount: number;
  /** What the customer handed over, for change (FR-10.3). */
  tendered?: number;
}

export interface PaymentResult {
  order_name: string;
  sales_invoice: string;
  total_amount: number;
  change_amount: number;
  status: string;
  /** Absent when the bill is outside the loyalty scheme (`D-189`). */
  loyalty_points_earned?: number;
  loyalty_balance?: number;
}

export interface EvenSplit {
  order_name: string;
  total_amount: number;
  ways: number;
  /** One amount per person, summing to `total_amount` exactly. */
  shares: number[];
}

export function getPaymentSummary(orderName: string): Promise<PaymentSummary> {
  return query<PaymentSummary>("payment.get_payment_summary", { order_name: orderName });
}

/**
 * What each person owes when a table asks to split the bill.
 *
 * Asked of the server rather than divided here: the shares are money
 * (`CLAUDE.md` §5.1), and dividing 100.00 three ways without losing five
 * halalas is the entire difficulty — see `totals.split_evenly`.
 */
export function splitEvenly(orderName: string, ways: number): Promise<EvenSplit> {
  return query<EvenSplit>("payment.split_evenly", { order_name: orderName, ways });
}

export function previewTotals(
  orderName: string,
  discountType: "percentage" | "amount" | null,
  discountValue: number,
  promotion: string | null = null,
  loyaltyPoints = 0,
): Promise<TotalsPreview> {
  return query<TotalsPreview>("payment.preview_totals", {
    order_name: orderName,
    discount_type: discountType,
    discount_value: discountValue,
    promotion,
    loyalty_points: loyaltyPoints,
  });
}

/**
 * A promotion this bill qualifies for (`D-165`).
 *
 * `is_auto_apply` off means the shop configured it to be **offered** rather
 * than taken — and until this list existed there was nowhere to offer it, so
 * such a promotion could be saved, listed as active, and do nothing.
 */
export interface PromotionOffer {
  name: string;
  title: string;
  title_ar: string;
  /** What it would take off this bill, so the cashier compares like with like. */
  benefit: number;
  is_auto_apply: 0 | 1;
  is_chosen: 0 | 1;
}

/**
 * What is on offer, and whether this cashier may pick one.
 *
 * The right travels with the list so the screen can say so **before** a choice
 * is made, rather than letting a cashier tell the customer a price the server
 * then refuses (`D-125`).
 */
export function promotionOffers(
  orderName: string,
): Promise<{ offers: PromotionOffer[]; may_choose: boolean }> {
  return query("payment.promotion_offers", { order_name: orderName });
}

export function processPayment(payload: {
  order_name: string;
  payments: PaymentLine[];
  discount_type?: string | null;
  discount_value?: number;
  /** The promotion the cashier picked, if any (`D-165`). */
  promotion?: string | null;
  manager_override_token?: string | null;
  /** Points the customer spends on this bill (`FR-10.5`, `D-189`). */
  loyalty_points_redeemed?: number;
}): Promise<PaymentResult> {
  return mutate<PaymentResult>("payment.process_payment", payload);
}

export function validateDiscountOverride(payload: {
  pin: string;
  percentage: number;
  reason: string;
  branch: string;
  pos_profile: string;
  order_name: string;
}): Promise<{ success: boolean; approved_by: string; override_token: string }> {
  // POST, never GET: the PIN must not reach a URL (04 §7, CLAUDE.md §5.4).
  return command("permissions.validate_discount_override", payload);
}

/**
 * Exchange a manager's PIN for a single-use token (07 §7).
 *
 * The general form: any `can_*` the cashier does not hold, or a rule that asks
 * for a second person regardless — `BR-055` refunds out of a counted shift
 * among them. `validateDiscountOverride` stays separate because a discount is
 * not a yes/no right: the approver's own ceiling has to cover the figure.
 */
export function validateManagerOverride(payload: {
  action_type: string;
  pin: string;
  reason: string;
  branch: string;
  pos_profile: string;
  order_name?: string | null;
}): Promise<{ success: boolean; approved_by: string; override_token: string }> {
  // POST, never GET: the PIN must not reach a URL (04 §7, CLAUDE.md §5.4).
  return command("permissions.validate_manager_override", payload);
}
