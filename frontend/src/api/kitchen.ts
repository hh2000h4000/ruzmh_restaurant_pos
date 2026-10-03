import { mutateOrQueue, type Queued } from "@/offline/queue";

import { mutate, query } from "./client";

export interface KotCreated {
  kot_name: string;
  production_center: string;
  kot_type: string;
  print_status: string;
}

export interface SendResult {
  kots_created: KotCreated[];
  /** Items no routing rule matched — BR-070 level 7 sends them to the till. */
  unrouted_items: string[];
  status: string;
}

/**
 * Deferrable. Losing this one hurts most: the cashier has told the customer the
 * food is ordered, and a dropped request means the kitchen never hears about it
 * and nobody finds out until the customer asks. Held on the device and replayed
 * on reconnect (09 §5).
 *
 * What it cannot do offline is print the ticket — that is Phase 3.
 */
export function sendToKitchen(orderName: string): Promise<SendResult | Queued> {
  return mutateOrQueue<SendResult>("kitchen.send_to_kitchen", { order_name: orderName });
}

/**
 * Put a ticket on paper again (FR-6.4, `D-211`).
 *
 * Not deferrable: it is asked for because a printer failed, and a request held
 * on the device during an outage would reach a printer nobody is waiting at.
 */
export function reprintKot(kotName: string): Promise<{ kot_name: string; print_status: string }> {
  return mutate("kitchen.reprint_kot", { kot_name: kotName });
}

export function getKots(orderName: string): Promise<KotCreated[]> {
  return query("kitchen.get_kots", { order_name: orderName });
}

/** How an unprinted ticket ended — the one word the bell shows (`D-298`). */
export type PrintAlertState = "failed" | "printing" | "printed" | "told";

export interface PrintAlert {
  kind: "print";
  /** The ticket — what the bell keys a row by, whatever its kind. */
  key: string;
  /** When it failed — what the bell orders by. */
  at: string;
  kot_name: string;
  restaurant_order: string;
  daily_number: number | null;
  call_name: string | null;
  table_number: string | null;
  station: string;
  station_ar: string;
  failed_at: string;
  state: PrintAlertState;
}

/**
 * The kitchen was told by hand, so the ticket stops alerting (`D-298`).
 *
 * Not deferrable, like the reprint: it answers an alert the server raised, and
 * the answer is only worth anything once the server has it.
 */
export function markKitchenTold(kotName: string): Promise<{ kot_name: string; state: PrintAlertState }> {
  return mutate("kitchen.mark_kitchen_told", { kot_name: kotName });
}
