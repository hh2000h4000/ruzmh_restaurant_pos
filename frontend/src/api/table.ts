import { query } from "./client";

export interface FloorTable {
  name: string;
  table_number: string;
  status: "available" | "occupied" | "reserved" | "cleaning" | "inactive";
  capacity: number;
  shape: string | null;
  current_order: string | null;
  /**
   * Every bill open on this table, oldest first — a table may carry more than
   * one where the branch allows it (`BR-066`). `current_order` names only one
   * of them and is kept for the desk; read this.
   */
  orders: TableBill[];
  /**
   * The day's next expected booking on this table, or `null` (`D-191`).
   *
   * `held` means the table is being kept for it right now — from one turn
   * before the booking to the end of the grace period — and an empty table then
   * reads `reserved`. Before that it is a note: the table still takes walk-ins.
   */
  reservation?: TableReservation | null;
}

export interface TableReservation {
  name: string;
  guest: string;
  party_size: number;
  /** `HH:MM`. */
  time: string;
  held: boolean;
}

export interface TableBill {
  name: string;
  daily_number: number | null;
  status: string;
  total_amount: number;
  /** Lines, not plates: two of the same dish is one row. */
  item_count: number;
  /** When the bill was opened. */
  opened_at: string;
}

export interface FloorPlan {
  section: { name: string; title: string; title_ar: string };
  floor_plan: { canvas_width: number; canvas_height: number };
  tables: FloorTable[];
}

export function getFloorPlan(section: string): Promise<FloorPlan> {
  return query<FloorPlan>("table.get_floor_plan", { section });
}
