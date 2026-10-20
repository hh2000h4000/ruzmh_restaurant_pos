<script setup lang="ts">
import { ref, watch } from "vue";

import AppIcon, { type IconName } from "@/components/AppIcon.vue";

/**
 * One tile for everything on the menu grid — a group, a dish, a layout button
 * (`D-192`).
 *
 * **Foodics' card, because the user pointed at it:** a picture on top, the name
 * under it, a coloured strip along the bottom. And **one component for every
 * grid on the panel** — the layout's buttons, the group browser, a group's
 * dishes and the search results — so a picture added to a group appears
 * wherever that group is drawn, and the four grids cannot drift apart (§5.5).
 *
 * **The picture is ERPNext's own** `image` field on the Item Group and the Item,
 * uploaded in the desk; a layout button may carry its own. **With none, or one
 * that fails to load** — offline, a file deleted, a private file — a drawn
 * placeholder stands in. A broken-image box on a till is a fault the cashier can
 * neither explain nor fix, and should never see.
 *
 * **The colour a manager gave a button colours the strip**, not the card. A
 * white card is what lets a picture read, and the strip keeps the colour's one
 * job: telling groups apart at a glance.
 *
 * **The picture gives way before the name does.** It takes whatever height the
 * tile has left, down to nothing: a menu of fifty groups packs its tiles small
 * (`D-142`), and there the name is what the cashier needs — not a sliver of a
 * photograph pushing the grid into a scroll.
 */
const props = withDefaults(
  defineProps<{
    label: string;
    image?: string | null;
    /** What stands in when there is no picture. */
    placeholder?: IconName;
    /** The strip along the bottom — a colour from configuration, or the theme's. */
    accent?: string | null;
    /** A second line under the name: a dish's price. */
    detail?: string | null;
    /** The detail is a warning, such as a dish with no price. */
    detailDanger?: boolean;
    disabled?: boolean;
    fontSize?: number | null;
    /**
     * A word over the picture's corner: "8 left", "Sold out" (`D-321`).
     *
     * **Only when there is something to say.** A tile with plenty behind it
     * shows nothing — "347" on every dish is a warehouse screen, and the
     * cashier's job is the queue. Two words in two tones, readable without the
     * colour.
     */
    badge?: string | null;
    /** The badge says it is gone, not merely running low. */
    badgeDanger?: boolean;
  }>(),
  {
    image: null,
    placeholder: "grid",
    accent: null,
    detail: null,
    detailDanger: false,
    disabled: false,
    fontSize: null,
    badge: null,
    badgeDanger: false,
  },
);

const emit = defineEmits<{ select: [] }>();

/** Set when the picture would not load; a new picture gets a new chance. */
const broken = ref(false);
watch(
  () => props.image,
  () => {
    broken.value = false;
  },
);
</script>

<template>
  <button
    type="button"
    class="flex min-w-0 flex-col overflow-hidden rounded-lg bg-surface text-center transition duration-100 ease-rpos active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
    :style="{ '--tile-accent': accent || 'rgb(var(--rpos-primary))' }"
    :disabled="disabled"
    @click="emit('select')"
  >
    <!-- A white tile on the grey ground, the picture over a wash of the
         tile's own colour (`D-371`): a placeholder in the group's colour
         says which shelf it is from; a grey square said nothing. -->
    <span
      class="relative grid min-h-0 w-full flex-1 place-items-center overflow-hidden"
      :style="{ backgroundColor: 'color-mix(in srgb, var(--tile-accent) 10%, rgb(var(--rpos-surface)))' }"
    >
      <img
        v-if="image && !broken"
        :src="image"
        alt=""
        loading="lazy"
        decoding="async"
        data-picture
        class="absolute inset-0 h-full w-full object-cover"
        @error="broken = true"
      >
      <AppIcon
        v-else
        :name="placeholder"
        :size="36"
        data-placeholder
        :style="{ color: 'var(--tile-accent)' }"
      />
      <span
        v-if="badge"
        data-badge
        class="absolute start-1.5 top-1.5 rounded-full px-2 py-0.5 text-xs font-bold shadow-card"
        :class="badgeDanger ? 'bg-danger text-white' : 'border border-line-strong bg-surface text-content'"
      >{{ badge }}</span>
    </span>

    <span class="flex shrink-0 flex-col gap-0.5 px-2 py-2.5">
      <span
        class="line-clamp-2 font-semibold leading-snug"
        :style="fontSize ? { fontSize: `${fontSize}px` } : undefined"
      >{{ label }}</span>
      <span
        v-if="detail"
        class="rpos-numeric text-sm"
        :class="detailDanger ? 'font-bold text-danger' : 'text-subtle'"
      >{{ detail }}</span>
    </span>

    <span
      data-accent
      class="h-1 w-full shrink-0"
      :style="{ backgroundColor: accent || 'rgb(var(--rpos-primary))' }"
    />
  </button>
</template>
