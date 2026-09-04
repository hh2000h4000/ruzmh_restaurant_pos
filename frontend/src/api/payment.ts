/**
 * Payment endpoints (07 §3, FR-10.x).
 *
 * `previewTotals` exists because the frontend must never compute money
 * (`CLAUDE.md` §5.1): the discount is applied on the server and the resulting
 * figures come back before anyone is charged.
 */
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

export interface PaymentSummary {
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

export interface TotalsPreview {
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
): Promise<TotalsPreview> {
  return query<TotalsPreview>("payment.preview_totals", {
    order_name: orderName,
    discount_type: discountType,
    discount_value: discountValue,
  });
}

export function processPayment(payload: {
  order_name: string;
  payments: PaymentLine[];
  discount_type?: string | null;
  discount_value?: number;
  manager_override_token?: string | null;
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
