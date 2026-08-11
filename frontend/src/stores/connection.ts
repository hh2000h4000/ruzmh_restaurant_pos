import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { ApiError, ping } from "@/api/client";
import { flush, failedCount, pendingCount } from "@/offline/queue";

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
