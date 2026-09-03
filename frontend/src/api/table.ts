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
}

export interface TableBill {
  name: string;
  daily_number: number | null;
  status: string;
  total_amount: number;
  /** Lines, not plates: two of the same dish is one row. */
  item_count: number;
  minutes: number;
}

export interface FloorPlan {
  section: { name: string; title: string; title_ar: string };
  floor_plan: { canvas_width: number; canvas_height: number };
  tables: FloorTable[];
}

export function getFloorPlan(section: string): Promise<FloorPlan> {
  return query<FloorPlan>("table.get_floor_plan", { section });
}
