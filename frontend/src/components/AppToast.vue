<script setup lang="ts">
import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n";
import { useNoticeStore } from "@/stores/notice";

/**
 * The one place a notice is drawn (`D-220`, §5.5).
 *
 * It floats above whatever it is placed over and takes no room: the notice it
 * replaces sat above the menu grid and pushed the dishes down every time a
 * receipt was printed.
 *
 * **Dark, and only as wide as it needs** (the user, on seeing the first one:
 * "make it narrower, two lines if the text is long, and a background that
 * stands out"). White on a white-and-warm screen was one more card among the
 * cards; the house ink reads as something that just happened. At most two
 * lines, so a long refusal wraps instead of widening across the dishes.
 *
 * **Both live regions are always in the page**, empty until something is said.
 * A region inserted with its words already inside is often not announced at all
 * (WCAG 4.1.3), so the regions stay and only their contents come and go. News is
 * `status` — read when the reader is free; a refusal is `alert` — read now.
 *
 * A finger or pointer on it holds it (WCAG 2.2.1): nobody reading slowly is
 * raced by the timer.
 */
const notice = useNoticeStore();

/**
 * It rises into place from just below and sinks away faster than it came — the
 * user asked for it to come up from underneath. The next one waits for the last
 * to leave, so two never cross. A device set to reduce motion gets none: the
 * notice simply appears (`motion-reduce`).
 */
const RISE = {
  enterActiveClass: "transition duration-300 ease-rpos motion-reduce:transition-none",
  enterFromClass: "translate-y-4 opacity-0",
  leaveActiveClass: "transition duration-150 ease-in motion-reduce:transition-none",
  leaveToClass: "translate-y-2 opacity-0",
  mode: "out-in" as const,
};
</script>

<template>
  <div class="pointer-events-none absolute inset-x-0 bottom-full z-20 mb-2 flex flex-col items-center px-3">
    <div
      role="status"
      class="flex w-full justify-center"
    >
      <Transition v-bind="RISE">
        <div
          v-if="notice.current?.kind === 'info'"
          :key="notice.current.id"
          class="pointer-events-auto flex max-w-[20rem] items-center gap-2.5 rounded-rpos bg-content py-2.5 text-sm leading-snug text-surface shadow-lift pe-1.5 ps-3.5"
          @pointerenter="notice.hold()"
          @pointerleave="notice.release()"
          @focusin="notice.hold()"
          @focusout="notice.release()"
        >
          <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-status-available text-white">
            <AppIcon
              name="check"
              :size="13"
            />
          </span>
          <span class="min-w-0 overflow-hidden [-webkit-box-orient:vertical] [-webkit-line-clamp:2] [display:-webkit-box]">
            {{ notice.current.text }}
          </span>
          <button
            type="button"
            class="shrink-0 rounded-rpos p-1.5 text-surface/60 hover:bg-surface/10 hover:text-surface"
            :aria-label="t('action.dismiss')"
            @click="notice.dismiss()"
          >
            <AppIcon
              name="close"
              :size="14"
            />
          </button>
        </div>
      </Transition>
    </div>

    <div
      role="alert"
      class="flex w-full justify-center"
    >
      <Transition v-bind="RISE">
        <div
          v-if="notice.current?.kind === 'error'"
          :key="notice.current.id"
          class="pointer-events-auto flex max-w-[20rem] items-center gap-2.5 rounded-rpos bg-danger py-2.5 text-sm leading-snug text-white shadow-lift pe-1.5 ps-3.5"
        >
          <span class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/20">
            <AppIcon
              name="ban"
              :size="13"
            />
          </span>
          <span class="min-w-0 overflow-hidden [-webkit-box-orient:vertical] [-webkit-line-clamp:2] [display:-webkit-box]">
            {{ notice.current.text }}
          </span>
          <button
            type="button"
            class="shrink-0 rounded-rpos p-1.5 text-white/75 hover:bg-white/15 hover:text-white"
            :aria-label="t('action.dismiss')"
            @click="notice.dismiss()"
          >
            <AppIcon
              name="close"
              :size="14"
            />
          </button>
        </div>
      </Transition>
    </div>
  </div>
</template>
