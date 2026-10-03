import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { getBell, markAnnouncementsRead, type BellItem } from "@/api/bell";
import { playTone } from "@/sound";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The bell (`D-298`, `D-299`, `D-303`): what did not print, and what the office
 * said — one list, newest first.
 *
 * **Read is kept where it belongs to.** A print alert is the branch's, and
 * which of them *this till* has looked at is a convenience of the screen, kept
 * on the device (`localStorage`, behind `try/catch`): a timestamp, and the
 * tickets read or struck off one by one. An announcement is addressed to a
 * person, and its sender needs to know who read it — so that is recorded on
 * the server, per cashier, and the device only remembers which rows it hid.
 */
interface Seen {
  since: string | null;
  read: string[];
  hidden: string[];
}

const STORAGE_KEY = "rpos.alerts.seen";

/** Enough for a long service; the oldest names fall off rather than grow for ever. */
const KEEP = 300;

function load(): Seen {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as Seen | null;
    if (stored && Array.isArray(stored.read) && Array.isArray(stored.hidden)) return stored;
  } catch {
    // Private window or blocked storage: start from today, below.
  }
  // A till seen for the first time owes nobody last month's failures: read
  // starts at the beginning of today.
  return { since: `${today()} 00:00:00`, read: [], hidden: [] };
}

function save(seen: Seen): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seen));
  } catch {
    // The badge still works for this session; it only forgets on reload.
  }
}

function today(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** What needs a hand now: an urgent announcement, or a ticket that never reached the kitchen. */
export function isUrgent(item: BellItem): boolean {
  return item.kind === "announcement" ? item.urgent : item.state === "failed";
}

export const useAlertsStore = defineStore("alerts", () => {
  const seen = ref<Seen>(load());

  /** The newest page — what the badge counts, whatever page the list is on. */
  const latest = ref<BellItem[]>([]);
  const rows = ref<BellItem[]>([]);
  const start = ref(0);
  const page = ref(20);
  const more = ref(false);
  const loading = ref(false);
  const failure = ref<string | null>(null);
  /** This cashier's unread announcements on the server, past this page too. */
  const unreadAnnouncements = ref(0);
  /** Bumped to open the bell on its unread tab — the drawer just opened (`D-303`). */
  const opened = ref(0);

  /** Items already announced, so a chime is one per item and never per refresh. */
  let heard: Set<string> | null = null;
  let asking = false;
  let again = false;

  function isUnread(item: BellItem): boolean {
    if (item.kind === "announcement") return !item.read;
    if (seen.value.read.includes(item.key)) return false;
    return !seen.value.since || item.at > seen.value.since;
  }

  const visible = computed(() => rows.value.filter((row) => !seen.value.hidden.includes(row.key)));
  const unread = computed(
    () =>
      latest.value.filter(
        (row) => row.kind === "print" && !seen.value.hidden.includes(row.key) && isUnread(row),
      ).length + unreadAnnouncements.value,
  );

  async function fetch(at: number) {
    const profile = useSessionStore().profile?.name;
    if (!profile) return null;
    // Offline the bell keeps what it last heard; the panel says why it is not newer.
    if (!useConnectionStore().isOnline) return null;
    return getBell(profile, at);
  }

  /** The newest page: the badge, and the list when it is showing the newest. */
  async function refresh(): Promise<void> {
    // One question at a time, and never a queue of them — the open orders'
    // rule (`D-180`): asked again while asking, it asks once more when done,
    // so an answer the cashier just gave is never left out.
    if (asking) {
      again = true;
      return;
    }
    asking = true;
    loading.value = true;
    try {
      const answer = await fetch(0);
      if (!answer) return;
      latest.value = answer.items;
      page.value = answer.page;
      unreadAnnouncements.value = answer.unread_announcements;
      if (start.value === 0) {
        rows.value = answer.items;
        more.value = answer.more;
      }
      failure.value = null;
      announce();
    } catch (cause) {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
      asking = false;
    }
    if (again) {
      again = false;
      await refresh();
    }
  }

  /** The user's rule: a page at a time, and a page replaces the one before it. */
  async function turn(to: number): Promise<void> {
    loading.value = true;
    try {
      const answer = await fetch(to);
      if (!answer) return;
      start.value = to;
      rows.value = answer.items;
      more.value = answer.more;
      failure.value = null;
    } catch (cause) {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  /** Once per new item, never repeated (the user's choice), as this terminal is set (`D-301`). */
  function chime(): void {
    const profile = useSessionStore().profile;
    if (profile?.rpos_alert_sound === 0) return;
    playTone(profile?.rpos_alert_tone, profile?.rpos_alert_volume);
  }

  function announce(): void {
    const fresh = latest.value.filter(isUnread).map((row) => row.key);
    // The first read of a session only learns what is there: a till switched on
    // does not chime for the morning's alerts.
    if (heard && fresh.some((key) => !heard!.has(key))) chime();
    heard = new Set([...(heard ?? []), ...fresh]);
  }

  function remember(change: Partial<Seen>): void {
    const next = { ...seen.value, ...change };
    next.read = next.read.slice(-KEEP);
    next.hidden = next.hidden.slice(-KEEP);
    seen.value = next;
    save(next);
  }

  /** One item read: on this till for a ticket, on the server for an announcement. */
  async function markRead(item: BellItem): Promise<void> {
    if (item.kind === "announcement") {
      if (!item.read) await markAnnouncementsRead(item.key);
      return;
    }
    if (!seen.value.read.includes(item.key)) remember({ read: [...seen.value.read, item.key] });
  }

  /** Everything read: tickets up to the newest on this till, and this cashier's announcements. */
  async function markAllRead(): Promise<void> {
    const newest = latest.value
      .filter((row) => row.kind === "print")
      .reduce((at, row) => (row.at > at ? row.at : at), seen.value.since ?? "");
    remember({ since: newest || seen.value.since, read: [] });
    if (unreadAnnouncements.value) {
      await markAnnouncementsRead();
      await refresh();
    }
  }

  function hide(key: string): void {
    remember({ hidden: [...seen.value.hidden, key] });
  }

  /**
   * The drawer just opened: if the office said something this cashier has not
   * read, open the bell on it, as Toast's pre-shift notes do (`D-303`).
   */
  async function showUnreadAnnouncements(): Promise<void> {
    await refresh();
    if (unreadAnnouncements.value) opened.value += 1;
  }

  return {
    rows: visible,
    unread,
    unreadAnnouncements,
    opened,
    start,
    page,
    more,
    loading,
    failure,
    isUnread,
    refresh,
    turn,
    markRead,
    markAllRead,
    hide,
    showUnreadAnnouncements,
  };
});
