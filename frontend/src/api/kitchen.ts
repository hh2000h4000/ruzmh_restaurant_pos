import { mutateOrQueue, type Queued } from "@/offline/queue";

import { query } from "./client";

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

export function getKots(orderName: string): Promise<KotCreated[]> {
  return query("kitchen.get_kots", { order_name: orderName });
}
