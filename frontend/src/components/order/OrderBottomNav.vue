<script setup lang="ts">
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { formatNumber, t, type MessageKey } from "@/i18n";

/**
 * Where the cashier goes, along the bottom of the order screen.
 *
 * **Navigation, not actions.** Nothing here touches the order in hand — that is
 * the row above the menu (D-037). The distinction is the whole reason the two
 * bars can coexist: this one changes what you are looking at, that one changes
 * what you have.
 *
 * This replaces the tab strip from `D-039`. Same job, and one control is better
 * than two — the reference system puts it here, a thumb rests here, and the
 * entries read as places rather than as a filter over the menu.
 *
 * **It sits under the working column, not across the window.** The bill runs
 * the full height beside it: it is the tallest thing on the screen because it
 * is the thing being read. A bar spanning both columns would cut the bill off
 * at the ankles to make room for a control that has nothing to do with it.
 *
 * Buttons are 56px, not the 70px of the till screen's action bar. That bar
 * carries the day's work and earns the weight; this one is a signpost, and a
 * signpost that shouts takes room from the menu. 56 still clears the 48px
 * minimum a finger needs (`--rpos-tap-target`) with room to spare.
 */
export interface NavEntry {
  key: string;
  label: MessageKey;
  icon: IconName;
  /** Shown as a badge; omitted when there is nothing to count. */
  count?: number;
  /** Marked as the way forward rather than a place you are already in. */
  primary?: boolean;
}

defineProps<{ entries: NavEntry[]; active: string }>();
const emit = defineEmits<{ select: [key: string] }>();
</script>

<template>
  <nav class="flex shrink-0 items-center gap-1.5 rounded-rpos bg-surface p-1.5 shadow-card">
    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      class="flex h-[56px] flex-1 flex-col items-center justify-center gap-0.5 rounded-[0.75rem] text-xs font-semibold transition duration-200 ease-rpos"
      :class="[
        entry.primary
          ? 'bg-primary text-primary-contrast shadow-card hover:shadow-lift'
          : active === entry.key
            ? 'bg-primary/10 text-primary'
            : 'text-muted hover:bg-background hover:text-content',
      ]"
      :aria-current="active === entry.key ? 'page' : undefined"
      @click="emit('select', entry.key)"
    >
      <span class="relative">
        <AppIcon
          :name="entry.icon"
          :size="22"
        />
        <span
          v-if="entry.count"
          class="rpos-numeric absolute -top-1 grid h-4 min-w-[1rem] place-items-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-contrast start-full -ms-1.5"
        >{{ formatNumber(entry.count) }}</span>
      </span>
      {{ t(entry.label) }}
    </button>
  </nav>
</template>
