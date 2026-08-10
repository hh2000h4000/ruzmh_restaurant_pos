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

export function sendToKitchen(orderName: string): Promise<SendResult> {
  return mutate<SendResult>("kitchen.send_to_kitchen", { order_name: orderName });
}

export function getKots(orderName: string): Promise<KotCreated[]> {
  return query("kitchen.get_kots", { order_name: orderName });
}
