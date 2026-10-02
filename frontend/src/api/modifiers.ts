import { query } from "./client";

export interface ModifierOption {
  title: string;
  title_ar: string;
  price_effect: "none" | "add" | "subtract";
  price_amount: number;
  is_default: 0 | 1;
  /** The English name when `title` is a code — a combo's item (D-285). */
  label?: string;
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
  /**
   * Shown only while this option of that group is chosen — a combo item's own
   * groups, asked when that item is the one picked (D-289).
   */
  when?: { group: string; option: string } | null;
  /** The combo item these add-ons belong to, asked over the combo (D-292). */
  part?: { item: string; title: string; title_ar: string } | null;
}

export function getModifierGroups(groups: string[]): Promise<ModifierGroup[]> {
  return query<ModifierGroup[]>("session.get_modifier_groups", { groups });
}
