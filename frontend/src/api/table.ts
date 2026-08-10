import { query } from "./client";

export interface FloorTable {
  name: string;
  table_number: string;
  status: "available" | "occupied" | "reserved" | "cleaning" | "inactive";
  capacity: number;
  shape: string | null;
  current_order: string | null;
  order_status?: string;
  order_minutes?: number;
  item_count?: number;
}

export interface FloorPlan {
  section: { name: string; title: string; title_ar: string };
  floor_plan: { canvas_width: number; canvas_height: number };
  tables: FloorTable[];
}

export function getFloorPlan(section: string): Promise<FloorPlan> {
  return query<FloorPlan>("table.get_floor_plan", { section });
}
