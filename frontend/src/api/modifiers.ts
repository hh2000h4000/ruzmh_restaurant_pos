import { query } from "./client";

export interface ModifierOption {
  title: string;
  title_ar: string;
  price_effect: "none" | "add" | "subtract";
  price_amount: number;
  is_default: 0 | 1;
}

export interface ModifierGroup {
  name: string;
  title: string;
  title_ar: string;
  selection_type: "single" | "multiple";
  is_required: 0 | 1;
  min_selections: number;
  max_selections: number;
  options: ModifierOption[];
}

export function getModifierGroups(groups: string[]): Promise<ModifierGroup[]> {
  return query<ModifierGroup[]>("session.get_modifier_groups", { groups });
}
