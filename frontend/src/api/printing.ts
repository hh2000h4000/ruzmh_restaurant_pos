/**
 * Paper, asked for a second time (`FR-7.5`, `D-143`).
 *
 * One call for a sale and for a refund, because it is one question: put this
 * invoice on the cashier's printer again. Nothing is created — the reprint
 * renders the document that exists, so what comes out is what was issued.
 */
import { mutate } from "./client";

export function reprintReceipt(invoiceName: string): Promise<{
  invoice: string;
  order_name: string;
  queued: boolean;
}> {
  return mutate("printing.reprint_receipt", { invoice_name: invoiceName });
}
