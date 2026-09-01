<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import { useRouter } from "vue-router";

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
const router = useRouter();

function signIn(): void {
  // The app owns the sign-in screen now (`D-094`), so this is a route and not
  // a trip to `/login`. Sending a cashier to ERPNext's form would ask them for
  // an email address and a password on a machine with no keyboard.
  void router.push({ name: "sign-in" });
}

onMounted(connection.start);
onUnmounted(connection.stop);
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden bg-background font-sans text-content">
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

    <!--
      One grid row, `minmax(0, 1fr)` tall. The screen inside it is a grid item,
      so it stretches to exactly this height with no percentage to resolve and
      no way to push a bottom bar off the window. Screens own their own
      scrolling; this box never scrolls.
    -->
    <div class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] overflow-hidden">
      <RouterView />
    </div>
  </div>
</template>
