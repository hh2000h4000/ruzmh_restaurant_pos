/**
 * Gift cards at the till (`D-256`).
 *
 * Nothing here computes money. The balance the screen shows is the server's,
 * because the ledger is the server's (`CLAUDE.md` §5.1) — a figure the till
 * worked out itself could tell a guest they have credit they do not.
 */
import { mutate, query } from "./client";

export interface GiftCardBalance {
  gift_card: string;
  card_number: string;
  balance: number;
  expires_on: string | null;
}

export interface GiftCardSale {
  gift_card: string;
  card_number: string;
  amount: number;
  balance: number;
  journal_entry: string | null;
  /** True when the queue re-sent a sale the server had already made (`09` §8). */
  repeated?: boolean;
}

/** Sell one card: take the money now, the guest eats later. */
export function sellGiftCard(payload: {
  pos_profile: string;
  card_number: string;
  amount: number;
  mode_of_payment: string;
  customer?: string | null;
}): Promise<GiftCardSale> {
  return mutate("gift_card.sell", payload);
}

/**
 * What is on a card.
 *
 * Rejects rather than returning zero when the card cannot be used: *no such
 * card*, *switched off* and *expired* are three different things for the cashier
 * to say, and the server words each of them.
 */
export function lookupGiftCard(card_number: string): Promise<GiftCardBalance> {
  return query("gift_card.lookup", { card_number });
}
