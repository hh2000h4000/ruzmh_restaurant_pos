import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { getPrintAlerts, type PrintAlert } from "@/api/kitchen";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The bell (`D-298`, `D-299`): the branch's kitchen tickets that did not print,
 * and which of them this till has read.
 *
 * **Read is this till's, kept on the device.** It is a convenience of the one
 * screen — the badge going quiet once somebody standing here has looked — not
 * a record: what was done about a ticket is on the server ("I told the
 * kitchen", a reprint). So it lives in `localStorage`, behind `try/catch`, and
 * a wiped browser only makes old alerts unread again.
 *
 * Read is a timestamp and a short list: everything that failed before `since`
 * is read, and so is each ticket named in `read` (one answered on its own).
 * Hidden rows are the ones the cashier struck off with ✕.
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

/**
 * A short two-note chime, made rather than loaded — no file to ship or cache
 * offline. Once per new alert, never repeated: the user asked to hear one
 * arrive, not to be nagged by it. Silent where the browser will not play.
 */
function chime(): void {
  try {
    const Context =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Context) return;
    const audio = new Context();
    [880, 1320].forEach((pitch, step) => {
      const tone = audio.createOscillator();
      const volume = audio.createGain();
      tone.frequency.value = pitch;
      tone.connect(volume);
      volume.connect(audio.destination);
      const at = audio.currentTime + step * 0.18;
      volume.gain.setValueAtTime(0.0001, at);
      volume.gain.exponentialRampToValueAtTime(0.2, at + 0.02);
      volume.gain.exponentialRampToValueAtTime(0.0001, at + 0.16);
      tone.start(at);
      tone.stop(at + 0.17);
    });
    setTimeout(() => void audio.close(), 600);
  } catch {
    // No sound is better than a broken till.
  }
}

export const useAlertsStore = defineStore("alerts", () => {
  const seen = ref<Seen>(load());

  /** The newest page — what the badge counts, whatever page the list is on. */
  const latest = ref<PrintAlert[]>([]);
  const rows = ref<PrintAlert[]>([]);
  const start = ref(0);
  const page = ref(20);
  const more = ref(false);
  const loading = ref(false);
  const failure = ref<string | null>(null);

  /** Alerts already announced, so a chime is one per alert and never per refresh. */
  let heard: Set<string> | null = null;

  function isUnread(row: PrintAlert): boolean {
    if (seen.value.read.includes(row.kot_name)) return false;
    return !seen.value.since || row.failed_at > seen.value.since;
  }

  const visible = computed(() => rows.value.filter((row) => !seen.value.hidden.includes(row.kot_name)));
  const unread = computed(
    () => latest.value.filter((row) => !seen.value.hidden.includes(row.kot_name) && isUnread(row)).length,
  );

  async function fetch(at: number): Promise<{ alerts: PrintAlert[]; more: boolean; page: number } | null> {
    const profile = useSessionStore().profile?.name;
    if (!profile) return null;
    // Offline the bell keeps what it last heard; the panel says why it is not newer.
    if (!useConnectionStore().isOnline) return null;
    return getPrintAlerts(profile, at);
  }

  /** The newest page: the badge, and the list when it is showing the newest. */
  async function refresh(): Promise<void> {
    loading.value = true;
    try {
      const answer = await fetch(0);
      if (!answer) return;
      latest.value = answer.alerts;
      page.value = answer.page;
      if (start.value === 0) {
        rows.value = answer.alerts;
        more.value = answer.more;
      }
      failure.value = null;
      announce();
    } catch (cause) {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  /** The user's rule: twenty at a time, and a page replaces the one before it. */
  async function turn(to: number): Promise<void> {
    loading.value = true;
    try {
      const answer = await fetch(to);
      if (!answer) return;
      start.value = to;
      rows.value = answer.alerts;
      more.value = answer.more;
      failure.value = null;
    } catch (cause) {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  }

  function announce(): void {
    const fresh = latest.value.filter(isUnread).map((row) => row.kot_name);
    // The first read of a session only learns what is there: a till switched on
    // does not chime for the morning's alerts.
    if (heard && fresh.some((name) => !heard!.has(name))) chime();
    heard = new Set([...(heard ?? []), ...fresh]);
  }

  function remember(change: Partial<Seen>): void {
    const next = { ...seen.value, ...change };
    next.read = next.read.slice(-KEEP);
    next.hidden = next.hidden.slice(-KEEP);
    seen.value = next;
    save(next);
  }

  function markRead(kotName: string): void {
    if (!seen.value.read.includes(kotName)) remember({ read: [...seen.value.read, kotName] });
  }

  /** Everything up to the newest alert is read; the per-ticket list is no longer needed. */
  function markAllRead(): void {
    const newest = latest.value.reduce((at, row) => (row.failed_at > at ? row.failed_at : at), seen.value.since ?? "");
    remember({ since: newest || seen.value.since, read: [] });
  }

  function hide(kotName: string): void {
    remember({ hidden: [...seen.value.hidden, kotName] });
  }

  return {
    rows: visible,
    unread,
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
  };
});
