<script setup lang="ts">
import { onMounted, onUnmounted, watch } from "vue";
import { useRouter } from "vue-router";

import { pairedDevice } from "@/device";
import { t, tn } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
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

/**
 * A lost session takes the cashier to the pad, rather than to a banner about it
 * (`D-101`).
 *
 * There used to be a red bar here saying "not signed in", with a button that
 * sent them to ERPNext's login form. Once this app grew its own sign-in screen
 * the bar became absurd: it appeared **on** that screen, above the keypad, and
 * its button led back to the page it was already on.
 *
 * "Not signed in" has exactly one right response, so the app performs it
 * instead of offering it (`CLAUDE.md` §5.5).
 */
watch(
  () => connection.state,
  (state) => {
    if (state !== "unauthenticated") return;

    useAuthStore().forget();

    // **Unless this machine has never been paired** (`D-226`). A till being
    // installed is unauthenticated by definition — nobody can sign in on it yet,
    // because the PIN pad belongs to a terminal it does not know. This watcher
    // pushed it to the pad anyway, over the pairing screen, on every probe: the
    // guard sent it to pairing and the watcher took it straight back, so the
    // code box could not be reached at all.
    const at = router.currentRoute.value.name;
    if (!pairedDevice()) {
      if (at !== "setup") void router.push({ name: "setup" });
      return;
    }

    if (at !== "sign-in") void router.push({ name: "sign-in" });
  },
);

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
