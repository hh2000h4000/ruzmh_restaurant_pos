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
  <nav class="flex shrink-0 items-center gap-2 border-t border-line bg-surface px-4 py-2.5 shadow-bar">
    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      class="flex h-[70px] flex-1 flex-col items-center justify-center gap-1 rounded-rpos text-sm font-semibold transition duration-200 ease-rpos"
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
          :size="26"
        />
        <span
          v-if="entry.count"
          class="rpos-numeric absolute -top-1.5 grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-primary px-1 text-[11px] font-bold text-primary-contrast start-full -ms-2"
        >{{ formatNumber(entry.count) }}</span>
      </span>
      {{ t(entry.label) }}
    </button>
  </nav>
</template>
