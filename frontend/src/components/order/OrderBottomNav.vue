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
 * **On a phone the icon stands over the label** (`D-194`). The rule above was
 * about height; below 640px the shortage is width. Beside their icons, five
 * labels on a 412px Fold got a column each too narrow for «الأصناف», and every
 * one was cut. Stacked, the label has the whole column — and the strip keeps
 * its height, because its 60px already had room for both. The entries stay on
 * the bar rather than behind a menu: they are the places a cashier crosses
 * between every few seconds, and hiding them costs a tap every time.
 *
 * **Five equal columns on a card.** They were fixed-width and evenly spaced,
 * on the argument that stretched entries read as slabs rather than signposts.
 * Sized to the bar they read as a segmented control instead, which is what
 * they are — and the bar keeps its shape because the column above it does.
 *
 * **The one you are on is filled.** The earlier rule was that no entry should
 * outweigh another, since navigation is not worth shouting. That was answering
 * the wrong question: the fill is not emphasis on a destination, it is the
 * answer to *where am I* — and a tint alone is not visible across a counter.
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
  <nav
    class="grid shrink-0 grid-cols-5 gap-2 rounded-rpos-lg border border-line bg-surface p-2.5 max-sm:gap-1 max-sm:p-1.5"
  >
    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      data-nav-entry
      class="flex min-h-[3.75rem] min-w-0 items-center justify-center gap-2.5 rounded-rpos text-sm font-medium transition duration-200 ease-rpos max-sm:flex-col max-sm:gap-1 max-sm:px-1"
      :class="
        active === entry.key
          ? 'bg-primary text-primary-contrast'
          : 'text-muted hover:bg-background hover:text-content'
      "
      :aria-current="active === entry.key ? 'page' : undefined"
      @click="emit('select', entry.key)"
    >
      <!-- On a phone the count rides beside the icon, over the label. Where the
           row is wide this wrapper is `contents`, so its two children join the
           row and the count falls back behind the label. -->
      <span
        data-nav-icon
        class="contents max-sm:flex max-sm:items-center max-sm:gap-1.5"
      >
        <AppIcon
          :name="entry.icon"
          :size="18"
          class="shrink-0 opacity-85"
        />
        <!-- Beside the label, not floating over the icon. A count that overlaps
             what it counts is unreadable the moment it reaches two digits. -->
        <span
          v-if="entry.count"
          class="rpos-numeric grid h-[1.375rem] min-w-[1.375rem] shrink-0 place-items-center rounded-full px-1.5 text-xs sm:order-last"
          :class="
            active === entry.key
              ? 'bg-primary-contrast/20 text-primary-contrast'
              : 'bg-primary text-primary-contrast'
          "
        >{{ formatNumber(entry.count) }}</span>
      </span>
      <span class="max-w-full truncate">{{ t(entry.label) }}</span>
    </button>
  </nav>
</template>
