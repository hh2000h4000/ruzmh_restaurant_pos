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

export function getPaymentSummary(orderName: string): Promise<PaymentSummary> {
  return query<PaymentSummary>("payment.get_payment_summary", { order_name: orderName });
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
