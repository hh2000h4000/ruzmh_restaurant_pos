<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import { ApiError, ping } from "@/api/client";
import { t } from "@/i18n";

/**
 * Connection status is visible on every screen (06 §Design Principles 5).
 *
 * The active probe is more reliable than the browser's `online` event, which
 * only knows whether a network interface exists — not whether the bench is
 * reachable (09 §2).
 *
 * "Unreachable" and "not signed in" are different states and must not share a
 * message. Treating a 403 as an outage sends the cashier to diagnose a network
 * that is working perfectly.
 */
type Connection = "online" | "offline" | "unauthenticated";

const state = ref<Connection>("online");
let timer: number | undefined;

async function probe(): Promise<void> {
  try {
    await ping();
    state.value = "online";
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 0) {
      state.value = "offline";
    } else if (cause instanceof ApiError && cause.isPermissionDenied) {
      state.value = "unauthenticated";
    } else {
      state.value = "offline";
    }
  }
}

function signIn(): void {
  // Frappe owns authentication (04 §7); this app never sees credentials.
  window.location.href = `/login?redirect-to=${encodeURIComponent(window.location.pathname)}`;
}

onMounted(() => {
  window.addEventListener("online", probe);
  window.addEventListener("offline", () => (state.value = "offline"));
  timer = window.setInterval(probe, 10_000);
  void probe();
});

onUnmounted(() => {
  window.clearInterval(timer);
  window.removeEventListener("online", probe);
});
</script>

<template>
  <div class="min-h-screen bg-background font-sans text-content">
    <!-- Status is never colour alone (06 §Accessibility): a mark plus words. -->
    <div
      v-if="state === 'offline'"
      role="status"
      class="flex items-center justify-center gap-2 bg-status-reserved px-4 py-2 text-sm font-medium text-white"
    >
      <span aria-hidden="true">●</span>
      <span>{{ t("conn.offline") }}</span>
    </div>

    <div
      v-else-if="state === 'unauthenticated'"
      role="alert"
      class="flex flex-wrap items-center justify-center gap-3 bg-danger px-4 py-2 text-sm font-medium text-white"
    >
      <span>{{ t("conn.signedOut") }}</span>
      <button
        type="button"
        class="rounded-rpos bg-white/20 px-3 py-1 underline"
        @click="signIn"
      >
        {{ t("conn.signIn") }}
      </button>
    </div>

    <RouterView />
  </div>
</template>
