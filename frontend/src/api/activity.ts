import { command, query } from "@/api/client";

/** One thing that happened to a bill. */
export interface ActivityEntry {
  name: string;
  action: string;
  subject: string | null;
  at: string;
  user: string;
  user_name: string;
  /** Set when the action was also a sensitive one, worth marking. */
  audit_log: string | null;
  details: Record<string, unknown>;
}

/** The bill's story, oldest first — it is read as a sequence, not a list. */
export function timeline(orderName: string): Promise<ActivityEntry[]> {
  return query<ActivityEntry[]>("activity.timeline", { order_name: orderName });
}

/**
 * The two entries only the screen can produce (`D-106`).
 *
 * Nothing changes on the server when a cashier opens a held bill or walks away
 * from it, so nothing else would ever know it happened — and "who had this bill
 * open at nine" is a real question about a bill that came out wrong.
 */
export function recordView(orderName: string, action: "viewed" | "left"): Promise<unknown> {
  return command("activity.record_view", { order_name: orderName, action });
}
