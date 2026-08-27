<script setup lang="ts">
/**
 * The interface chrome's icons, inline.
 *
 * Emoji were what the screens used, and emoji are why they looked dated: each
 * platform draws its own, they carry their own colour, and they never line up
 * with a text baseline. These are stroked paths on a 24-grid that inherit
 * `currentColor`, so an icon is the same weight as the label beside it and the
 * theme still owns the colour.
 *
 * No icon library: this is the whole set the app uses, and a dependency that
 * ships a thousand glyphs to send twenty is not a trade worth making.
 */

const PATHS = {
  search: "M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z",
  bell: "M15 17h5l-1.4-1.4A2 2 0 0118 14.2V11a6 6 0 10-12 0v3.2c0 .5-.2 1-.6 1.4L4 17h5m6 0a3 3 0 11-6 0m6 0H9",
  chevronDown: "M6 9l6 6 6-6",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  list: "M4 6h16M4 12h16M4 18h16",
  refresh: "M20 11a8 8 0 10-2.3 6.3M20 5v6h-6",
  logout: "M15 17l5-5-5-5M20 12H9M13 4H6a2 2 0 00-2 2v12a2 2 0 002 2h7",
  receipt: "M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6",
  calendar: "M7 3v3M17 3v3M4 9h16M5 6h14a1 1 0 011 1v12a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1z",
  chart: "M4 20h16M7 16v-5M12 16V6M17 16v-8",
  floorPlan: "M5 10h14M5 10a2 2 0 012-2h10a2 2 0 012 2M7 14v4M17 14v4M5 10v2a2 2 0 002 2h10a2 2 0 002-2v-2",
  sort: "M8 4v16M8 20l-3-3M8 4l3 3M16 20V4M16 4l-3 3M16 20l3-3",
  more: "M12 6h.01M12 12h.01M12 18h.01",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM6 20a6 6 0 0112 0",
  document: "M14 3v5h5M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8z",
  clock: "M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
} as const;

export type IconName = keyof typeof PATHS;

withDefaults(defineProps<{ name: IconName; size?: number }>(), { size: 20 });
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="PATHS[name]" />
  </svg>
</template>
