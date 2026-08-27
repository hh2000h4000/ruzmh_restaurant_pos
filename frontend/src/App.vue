<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";

import { t, tn } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";

/**
 * Connection status is visible on every screen (06 §Design Principles 5).
 *
 * The state itself lives in a store rather than here, because the queue depth
 * shown in this bar and the flush triggered on reconnect are the same concern
 * (09 §10).
 */
const connection = useConnectionStore();

function signIn(): void {
  // Frappe owns authentication (04 §7); this app never sees credentials.
  window.location.href = `/login?redirect-to=${encodeURIComponent(window.location.pathname)}`;
}

onMounted(connection.start);
onUnmounted(connection.stop);
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-background font-sans text-content">
    <!-- Status is never colour alone (06 §Accessibility): a mark plus words. -->
    <div
      v-if="connection.state === 'offline'"
      role="status"
      class="flex flex-wrap items-center justify-center gap-2 bg-status-reserved px-4 py-2 text-sm font-medium text-white"
    >
      <span aria-hidden="true">●</span>
      <span>{{ t("conn.offline") }}</span>
      <span v-if="connection.pending">— {{ tn("count.queued", connection.pending) }}</span>
    </div>

    <div
      v-else-if="connection.state === 'unauthenticated'"
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

    <!-- Online but still carrying work: the cashier must be able to see that
         the last few actions have not reached the server yet. -->
    <div
      v-else-if="connection.hasBacklog"
      role="status"
      class="flex flex-wrap items-center justify-center gap-2 bg-status-cleaning px-4 py-2 text-sm font-medium text-white"
    >
      <span v-if="connection.syncing">{{ t("conn.syncing") }}</span>
      <span v-else-if="connection.pending">{{ tn("count.queued", connection.pending) }}</span>
      <template v-if="connection.failed">
        <span>{{ tn("count.syncFailed", connection.failed) }}</span>
      </template>
      <button
        v-if="!connection.syncing"
        type="button"
        class="rounded-rpos bg-white/20 px-3 py-1 underline"
        @click="connection.drain"
      >
        {{ t("conn.syncNow") }}
      </button>
    </div>

    <!-- `min-h-0` is what lets a screen inside this column shrink instead of
         pushing the bar off the bottom of the window. -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <RouterView />
    </div>
  </div>
</template>
