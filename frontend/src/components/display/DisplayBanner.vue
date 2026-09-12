<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";

/**
 * The restaurant's banners, turning (`FR-13.1`, `D-203`).
 *
 * One component for both places it appears — filling the screen while the till
 * is idle, and beside a bill once one is open. The rule for *which* banner is
 * showing lives here once, so the two placements cannot drift apart
 * (`CLAUDE.md` §5.5).
 *
 * **A single banner gets no timer.** Nothing would change on screen, and a
 * second-by-second interval on a screen that runs all day is a cost with no
 * effect.
 */
const props = defineProps<{ banners: string[]; seconds: number }>();

/** Below this a banner is gone before it can be read; the desk default is 8. */
const FLOOR_SECONDS = 2;

const at = ref(0);
let timer: number | undefined;

function restart(): void {
  window.clearInterval(timer);
  at.value = 0;

  if (props.banners.length < 2) return;

  timer = window.setInterval(
    () => {
      at.value = (at.value + 1) % props.banners.length;
    },
    Math.max(FLOOR_SECONDS, props.seconds) * 1000,
  );
}

watch(() => [props.banners, props.seconds], restart, { immediate: true, deep: true });
onUnmounted(() => window.clearInterval(timer));

const current = computed(() => props.banners[at.value] ?? null);
</script>

<template>
  <div
    v-if="current"
    data-banner
    class="grid min-h-0 place-items-center overflow-hidden bg-surface"
  >
    <!-- `alt` is empty on purpose: the picture carries its own words, and a
         guest-facing screen reading out a filename helps nobody. -->
    <Transition
      mode="out-in"
      enter-active-class="transition-opacity duration-500"
      enter-from-class="opacity-0"
      leave-active-class="transition-opacity duration-300"
      leave-to-class="opacity-0"
    >
      <img
        :key="current"
        :src="current"
        alt=""
        class="h-full w-full object-contain"
      >
    </Transition>
  </div>
</template>
