import { defineStore } from "pinia";
import { ref } from "vue";

import { getStock, setSoldOut } from "@/api/availability";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/** What a tile says about its item, if anything. */
export interface StockMark {
  /** Finished: marked by a person, or none left. */
  finished: boolean;
  /** How many are left, when that is worth saying. */
  left: number | null;
  /** The till will refuse it, so the tile does not offer it. */
  blocked: boolean;
}

/**
 * What is finished and what is running low in this branch (`D-321`, `D-322`).
 *
 * **Information, never the decision.** The figures are seconds old by design —
 * the server shares one reading between the branch's tills — and the refusal
 * is the server's, when the line is added. A tile that is a little behind
 * costs a tap and a message; a till that waited on stock for every tile would
 * cost the queue.
 *
 * Asked on the bell's timer, and it fails quietly: with no answer the tiles
 * simply say nothing, which is what they said before this existed.
 */
export const useStockStore = defineStore("stock", () => {
  const enforced = ref(false);
  const left = ref<Record<string, number>>({});
  const soldOut = ref<Set<string>>(new Set());
  let asking = false;

  async function refresh(): Promise<void> {
    const profile = useSessionStore().profile?.name;
    if (!profile || asking || !useConnectionStore().isOnline) return;

    asking = true;
    try {
      const stock = await getStock(profile);
      enforced.value = stock.enforced;
      left.value = stock.left;
      soldOut.value = new Set(stock.sold_out);
    } catch {
      // The tiles keep what they last knew; the server still decides.
    } finally {
      asking = false;
    }
  }

  /** Mark an item finished for today, or bring it back. Throws what the server said. */
  async function mark(item: string, finished: boolean): Promise<void> {
    const profile = useSessionStore().profile?.name;
    if (!profile) return;
    soldOut.value = new Set((await setSoldOut(profile, item, finished)).sold_out);
  }

  function of(item: string): StockMark | null {
    if (soldOut.value.has(item)) return { finished: true, left: null, blocked: true };

    const count = left.value[item];
    if (count === undefined) return null;
    // A branch that does not enforce still sells it: the number is a warning.
    if (count <= 0) return { finished: true, left: null, blocked: enforced.value };
    return { finished: false, left: count, blocked: false };
  }

  return { enforced, left, soldOut, refresh, mark, of };
});
