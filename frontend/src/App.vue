<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import { ping } from "@/api/client";

/**
 * Connection status is visible on every screen (06 §Design Principles 5).
 *
 * The active probe is more reliable than the browser's `online` event, which
 * only knows whether a network interface exists — not whether the bench is
 * reachable (09 §2).
 */
const online = ref(navigator.onLine);
const probing = ref(false);
let timer: number | undefined;

async function probe(): Promise<void> {
  probing.value = true;
  try {
    await ping();
    online.value = true;
  } catch {
    online.value = false;
  } finally {
    probing.value = false;
  }
}

onMounted(() => {
  window.addEventListener("online", probe);
  window.addEventListener("offline", () => (online.value = false));
  timer = window.setInterval(probe, 10_000);
  void probe();
});

onUnmounted(() => {
  window.clearInterval(timer);
  window.removeEventListener("online", probe);
});
</script>

<template>
  <div class="min-h-screen bg-background text-content font-sans">
    <!--
      Status is never colour alone (06 §Accessibility): every indicator pairs a
      dot with a word.
    -->
    <div
      v-if="!online"
      role="status"
      class="flex items-center justify-center gap-2 bg-status-reserved px-4 py-2 text-sm font-medium text-white"
    >
      <span aria-hidden="true">●</span>
      <span>وضع عدم الاتصال — العمليات تُحفظ محلياً</span>
    </div>

    <RouterView />
  </div>
</template>
