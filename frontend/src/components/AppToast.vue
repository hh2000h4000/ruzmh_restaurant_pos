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
 * **Both live regions are always in the page**, empty until something is said.
 * A region inserted with its words already inside is often not announced at all
 * (WCAG 4.1.3), so the regions stay and only their contents come and go. News is
 * `status` — read when the reader is free; a refusal is `alert` — read now.
 *
 * A finger or pointer on it holds it (WCAG 2.2.1): nobody reading slowly is
 * raced by the timer.
 */
const notice = useNoticeStore();
</script>

<template>
  <div class="pointer-events-none absolute inset-x-0 bottom-full z-20 mb-2 flex flex-col items-center px-3">
    <div
      role="status"
      class="w-full max-w-md"
    >
      <div
        v-if="notice.current?.kind === 'info'"
        :key="notice.current.id"
        class="pointer-events-auto flex items-center gap-3 rounded-rpos border border-line bg-surface px-4 py-3 text-sm shadow-lift"
        @pointerenter="notice.hold()"
        @pointerleave="notice.release()"
        @focusin="notice.hold()"
        @focusout="notice.release()"
      >
        <AppIcon
          name="check"
          :size="18"
          class="shrink-0 text-status-available"
        />
        <span class="min-w-0 flex-1">{{ notice.current.text }}</span>
        <button
          type="button"
          class="shrink-0 rounded-rpos p-1 text-muted hover:bg-background"
          :aria-label="t('action.dismiss')"
          @click="notice.dismiss()"
        >
          <AppIcon
            name="close"
            :size="16"
          />
        </button>
      </div>
    </div>

    <div
      role="alert"
      class="w-full max-w-md"
    >
      <div
        v-if="notice.current?.kind === 'error'"
        :key="notice.current.id"
        class="pointer-events-auto flex items-center gap-3 rounded-rpos border border-danger/40 bg-surface px-4 py-3 text-sm text-danger shadow-lift"
      >
        <AppIcon
          name="ban"
          :size="18"
          class="shrink-0"
        />
        <span class="min-w-0 flex-1">{{ notice.current.text }}</span>
        <button
          type="button"
          class="shrink-0 rounded-rpos p-1 hover:bg-danger/10"
          :aria-label="t('action.dismiss')"
          @click="notice.dismiss()"
        >
          <AppIcon
            name="close"
            :size="16"
          />
        </button>
      </div>
    </div>
  </div>
</template>
