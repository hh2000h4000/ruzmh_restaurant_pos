import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { ApiError, ping } from "@/api/client";
import { pairedDevice } from "@/device";
import { flush, failedCount, pendingCount } from "@/offline/queue";
import { useSessionStore } from "@/stores/session";

/**
 * Connectivity, and the queue depth that goes with it (09 §2, §10).
 *
 * The active probe is more reliable than the browser's `online` event, which
 * only knows whether a network interface exists — not whether the bench is
 * reachable. A terminal on restaurant Wi-Fi with a dead uplink reports itself
 * online all day.
 *
 * "Unreachable" and "not signed in" are different states and must not share a
 * message (`D-027`). Treating a 403 as an outage sends the cashier to diagnose
 * a network that is working perfectly — and queueing that 403 would replay a
 * refusal forever.
 */
export type ConnectionState = "online" | "offline" | "unauthenticated";

/** 09 §2. Slow enough not to be chatter, fast enough that a cashier notices. */
const PROBE_MS = 10_000;

export const useConnectionStore = defineStore("connection", () => {
  const state = ref<ConnectionState>("online");
  const pending = ref(0);
  const failed = ref(0);
  const syncing = ref(false);

  const isOnline = computed(() => state.value === "online");
  /** 09 §10 — the bar says "offline, N waiting", never just a colour. */
  const hasBacklog = computed(() => pending.value > 0 || failed.value > 0);

  let timer: number | undefined;

  async function refreshCounts(): Promise<void> {
    pending.value = await pendingCount();
    failed.value = await failedCount();
  }

  async function drain(): Promise<void> {
    if (syncing.value) return;

    syncing.value = true;
    try {
      await flush();
    } finally {
      syncing.value = false;
      await refreshCounts();
    }
  }

  async function probe(): Promise<void> {
    const was = state.value;

    try {
      await ping();
      state.value = "online";
    } catch (cause) {
      if (cause instanceof ApiError && cause.isPermissionDenied) {
        state.value = "unauthenticated";
      } else {
        state.value = "offline";
      }
    }

    if (state.value === "online" && was !== "online") {
      // The connection just came back. Everything held on this device goes now,
      // before the cashier can act on stale state.
      await drain();
      await refreshTerminal();
    }
  }

  function start(): void {
    if (timer !== undefined) return;

    window.addEventListener("online", probe);
    window.addEventListener("offline", markOffline);
    timer = window.setInterval(probe, PROBE_MS);

    void refreshCounts();
    void probe();
  }

  function stop(): void {
    window.clearInterval(timer);
    timer = undefined;
    window.removeEventListener("online", probe);
    window.removeEventListener("offline", markOffline);
  }

  function markOffline(): void {
    state.value = "offline";
  }

  /**
   * Fetch the terminal again when it is running on yesterday's copy (`D-230`).
   *
   * A till that starts while the server is down keeps selling from the cached
   * configuration (09 §3) — the right thing to do. But nothing then replaced
   * it: the cache stayed in hand until somebody thought to reload the page,
   * long after the server was back.
   *
   * The user met it as a menu with **no prices on any tile** while the bill
   * above priced correctly. A price list added to an order type that morning
   * was simply not in the copy the till was holding, and no amount of signing
   * in and out reached it, because none of that re-fetches the terminal.
   *
   * Only when the payload in hand came from the cache: a session already loaded
   * from the server is current, and re-fetching it on every reconnection would
   * reset the screen for nothing.
   */
  async function refreshTerminal(): Promise<void> {
    const session = useSessionStore();
    if (!session.cachedAt) return;

    const paired = pairedDevice();
    const profile = session.profile?.name ?? paired?.posProfile;
    if (!profile) return;

    try {
      await session.load(profile, paired?.token);
    } catch {
      // Still not reachable, or refused. The cached copy stays, the banner
      // stays with it, and the next probe tries again.
    }
  }

  return {
    state,
    pending,
    failed,
    syncing,
    isOnline,
    hasBacklog,
    start,
    stop,
    probe,
    drain,
    refreshCounts,
  };
});
