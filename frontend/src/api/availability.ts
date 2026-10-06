import { mutate, query } from "./client";

/** What the tiles show about stock (`D-321`, `D-322`). */
export interface Stock {
  /** The branch refuses what it has none of; otherwise the numbers are for information. */
  enforced: boolean;
  /** Tiles show what is left from this many down. */
  low_at: number;
  /** Item → how many are left, **only for items at or under `low_at`**. */
  left: Record<string, number>;
  /** Items somebody marked as finished for today. */
  sold_out: string[];
}

export function getStock(posProfile: string): Promise<Stock> {
  return query("availability.get_stock", { pos_profile: posProfile });
}

/**
 * Mark an item finished for today in this branch, or bring it back.
 * Not deferrable: the other tills must stop selling it now, and offline nobody would know.
 */
export function setSoldOut(posProfile: string, item: string, soldOut: boolean): Promise<{ sold_out: string[] }> {
  return mutate("availability.set_sold_out", { pos_profile: posProfile, item, sold_out: soldOut ? 1 : 0 });
}
