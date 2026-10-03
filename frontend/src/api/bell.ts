import type { PrintAlert } from "./kitchen";
import { mutate, query } from "./client";

/** A message from the office to the people at the tills (`D-303`). */
export interface Announcement {
  kind: "announcement";
  key: string;
  at: string;
  subject: string;
  message: string;
  urgent: boolean;
  sender: string;
  /** Read by the signed-in cashier — recorded on the server, per person. */
  read: boolean;
}

export type BellItem = PrintAlert | Announcement;

export interface Bell {
  items: BellItem[];
  /** An older page exists. */
  more: boolean;
  /** Rows on a page — the server's number, so the two never step differently. */
  page: number;
  /** This cashier's unread announcements, all of them, not only this page's. */
  unread_announcements: number;
}

/** The bell: unprinted tickets and announcements, newest first, a page at a time (`D-298`, `D-303`). */
export function getBell(posProfile: string, start = 0): Promise<Bell> {
  return query("bell.get_bell", { pos_profile: posProfile, start });
}

/**
 * The signed-in cashier read one announcement, or every one when no name is given.
 * Not deferrable: the sender is waiting to see who read it.
 */
export function markAnnouncementsRead(name?: string): Promise<{ marked: number }> {
  return mutate("bell.mark_announcements_read", name ? { name } : {});
}
