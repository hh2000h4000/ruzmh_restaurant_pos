/**
 * Returns and refunds (FR-9, D-064).
 *
 * The only way to reverse a sale: cancelling the invoice is refused
 * (`BR-050a`). Nothing here works out an amount — the refund figure is the
 * credit note's own, computed by ERPNext on a document that is not saved until
 * the cashier confirms (`CLAUDE.md` §5.1).
 */
import { mutate, query } from "./client";

/** One line of a paid bill, and how much of it can still come back. */
export interface ReturnableLine {
  /** The original `Sales Invoice Item` — what a refund names, not the item code. */
  row: string;
  idx: number;
  item: string;
  item_name: string;
  qty: number;
  rate: number;
  amount: number;
  returned: number;
  returnable: number;
}

/**
 * Why a bill is being reversed (D-065).
 *
 * A code, not a sentence: a KSA credit note carries the reason and its text has
 * to map to one of five triggers ZATCA recognises. The server owns the list;
 * the screen only labels it.
 */
export type ReturnReason =
  | "goods_returned"
  | "quality_complaint"
  | "wrong_item"
  | "price_error"
  | "order_cancelled";

export interface Returnable {
  order_name: string;
  sales_invoice: string;
  items: ReturnableLine[];
  reasons: ReturnReason[];
  /** BR-054 — every method the terminal has; the cashier picks (D-066). */
  methods: string[];
  /** BR-054 — the refund goes back the way the money came in. */
  paid_with: { method: string; amount: number }[];
  returns: { name: string; posting_date: string; grand_total: number }[];
  fully_returned: boolean;
}

export interface ReturnLine {
  row: string;
  qty: number;
}

export function getReturnable(orderName: string): Promise<Returnable> {
  return query<Returnable>("returns.get_returnable", { order_name: orderName });
}

export function previewReturn(
  orderName: string,
  items: ReturnLine[],
): Promise<{ refund_amount: number; net_amount: number; tax_amount: number }> {
  return query("returns.preview_return", { order_name: orderName, items });
}

/**
 * Not deferrable, and the reason is the sharpest in the app: a refund replayed
 * once hands the customer their money back twice. It carries a `queue_id` like
 * every write, so a retry after a dropped connection returns the first result
 * rather than paying again (09 §8).
 */
export function createReturn(payload: {
  order_name: string;
  items: ReturnLine[];
  reason_code: ReturnReason;
  note?: string | null;
  refund_method?: string | null;
  manager_override_token?: string | null;
}): Promise<{
  order_name: string;
  sales_invoice: string;
  credit_note: string;
  refund_amount: number;
  returnable: Returnable;
}> {
  return mutate("returns.create_return", payload);
}
