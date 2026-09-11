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
  }>(),
  {
    image: null,
    placeholder: "grid",
    accent: null,
    detail: null,
    detailDanger: false,
    disabled: false,
    fontSize: null,
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
    class="flex min-w-0 flex-col overflow-hidden rounded-rpos border border-line bg-surface text-center shadow-card transition duration-200 ease-rpos hover:-translate-y-0.5 hover:shadow-lift disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0 disabled:hover:shadow-card"
    :disabled="disabled"
    @click="emit('select')"
  >
    <span class="relative grid min-h-0 w-full flex-1 place-items-center overflow-hidden bg-background">
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
        class="text-muted"
      />
    </span>

    <span class="flex shrink-0 flex-col gap-0.5 px-2 py-2.5">
      <span
        class="line-clamp-2 font-semibold leading-snug"
        :style="fontSize ? { fontSize: `${fontSize}px` } : undefined"
      >{{ label }}</span>
      <span
        v-if="detail"
        class="rpos-numeric text-sm font-bold"
        :class="detailDanger ? 'text-danger' : 'text-primary'"
      >{{ detail }}</span>
    </span>

    <span
      data-accent
      class="h-1.5 w-full shrink-0 bg-primary"
      :style="accent ? { backgroundColor: accent } : undefined"
    />
  </button>
</template>
