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
 * **One line, icon beside label.** Stacking the icon over the label made the
 * strip twice as tall for no more information — and the height came out of the
 * menu, which is the part a cashier actually works in. The till screen's action
 * bar stacks and is 70px tall because it carries the day's work; this one only
 * says where you are. At 48px it is exactly the minimum a finger needs
 * (`--rpos-tap-target`) and not a pixel more.
 *
 * **Fixed width, not stretched.** Entries sized to the bar make each button a
 * quarter of the screen wide, which reads as four slabs rather than four
 * signposts — and the widths then shift whenever the column does. 104px spaced
 * evenly keeps the bar the same shape on every terminal.
 *
 * Every entry carries the same weight. One filled block among four is a shout,
 * and what would be shouted is navigation.
 */
export interface NavEntry {
  key: string;
  label: MessageKey;
  icon: IconName;
  /** Shown as a badge; omitted when there is nothing to count. */
  count?: number;
}

defineProps<{ entries: NavEntry[]; active: string }>();
const emit = defineEmits<{ select: [key: string] }>();
</script>

<template>
  <nav class="flex shrink-0 items-center justify-around gap-1 rounded-rpos bg-surface p-1 shadow-card">
    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      class="flex h-tap w-[104px] shrink-0 items-center justify-center gap-2 rounded-[0.75rem] text-sm font-semibold transition duration-200 ease-rpos"
      :class="
        active === entry.key
          ? 'bg-primary/10 text-primary'
          : 'text-muted hover:bg-background hover:text-content'
      "
      :aria-current="active === entry.key ? 'page' : undefined"
      @click="emit('select', entry.key)"
    >
      <span
        class="relative shrink-0"
        :class="active === entry.key ? '' : 'text-primary'"
      >
        <AppIcon
          :name="entry.icon"
          :size="18"
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
