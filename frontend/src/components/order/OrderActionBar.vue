<script setup lang="ts">
import { ref } from "vue";

import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { useDismiss } from "@/composables/useDismiss";
import { t, type MessageKey } from "@/i18n";

/**
 * The order's actions: the few a cashier repeats, then everything else.
 *
 * **Why not every button at once.** Our permission set has sixteen `can_*`
 * flags, so a manager sees a full toolbar and a cashier sees two entries — a
 * fixed grid built for the full set breaks into holes and wrapped rows for
 * everyone else. A short row plus a menu shrinks cleanly.
 *
 * **Destructive actions do not belong in the row.** Cancelling an order sits
 * in the menu, one deliberate tap further away, because the row is where a
 * busy hand lands without looking.
 *
 * **On a phone the corrections are icons** (`D-194`). Four labelled buttons
 * need 551px and a 412px Fold gives the row 376, so it broke onto a second
 * line. Only the
 * primary keeps its words; the note, refresh and «المزيد» become squares, and
 * each still carries its label for a screen reader. The note stays in the row
 * rather than moving into the menu — an allergy is still one tap away.
 *
 * **The order never changes.** A cashier learns positions by hand, not by eye;
 * sorting by recent use would move the target every shift. Permissions may
 * remove an entry, but the survivors keep their order.
 */
export interface OrderAction {
  key: string;
  label: MessageKey;
  icon: IconName;
  disabled?: boolean;
  /** Rendered in the danger colour and kept out of the primary row. */
  destructive?: boolean;
  /**
   * The one that moves the order forward, filled in the brand colour.
   *
   * At most one. Two filled buttons in a row is the same as none — the eye has
   * nothing to land on — which is why this is a flag on a single action rather
   * than a style each caller picks.
   */
  primary?: boolean;
}

defineProps<{ actions: OrderAction[]; more: OrderAction[] }>();
const emit = defineEmits<{ select: [action: OrderAction] }>();

const menuOpen = ref(false);

/** A tap anywhere else puts the sheet away — it covers the item grid. */
const menuAnchor = useDismiss(menuOpen);

function choose(action: OrderAction): void {
  if (action.disabled) return;
  menuOpen.value = false;
  emit("select", action);
}
</script>

<template>
  <div class="flex flex-wrap items-stretch gap-2.5 max-sm:flex-nowrap max-sm:gap-2">
    <!-- Square keys, icon over word, white on the screen's grey — the row a hand
         finds without reading (`D-371`). -->
    <!-- One line on a phone: the primary takes what the squares leave, and
         would sooner shorten its label than push them onto a second row.
         Inside the root, not above it — a comment there makes a fragment. -->
    <button
      v-for="action in actions"
      :key="action.key"
      type="button"
      class="flex min-h-[4.75rem] min-w-[5.5rem] flex-col items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-sm font-medium transition duration-100 ease-rpos active:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-40 max-sm:min-h-[3.375rem]"
      :class="
        action.primary
          ? 'bg-primary/10 text-primary max-sm:min-w-0 max-sm:flex-1 max-sm:flex-row max-sm:px-4'
          : 'bg-surface text-content max-sm:w-[3.375rem] max-sm:min-w-0 max-sm:shrink-0 max-sm:px-0'
      "
      :disabled="action.disabled"
      @click="choose(action)"
    >
      <AppIcon
        :name="action.icon"
        :size="24"
        class="shrink-0 text-secondary"
      />
      <span :class="action.primary ? 'truncate' : 'max-sm:sr-only'">{{ t(action.label) }}</span>
    </button>

    <div
      v-if="more.length"
      ref="menuAnchor"
      class="relative max-sm:shrink-0"
    >
      <button
        type="button"
        class="flex h-full min-h-[4.75rem] min-w-[5.5rem] flex-col items-center justify-center gap-1.5 whitespace-nowrap rounded-lg bg-surface px-3 text-sm font-medium transition duration-100 ease-rpos active:bg-primary/10 max-sm:min-h-[3.375rem] max-sm:w-[3.375rem] max-sm:min-w-0 max-sm:px-0"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <AppIcon
          name="moreHorizontal"
          :size="24"
          class="shrink-0 text-secondary"
        />
        <span class="max-sm:sr-only">{{ t("order.more") }}</span>
      </button>

      <!-- On a phone the trigger sits at the row's far end, so the sheet opens
           back across the screen from that edge instead of off it. -->
      <div
        v-if="menuOpen"
        class="absolute top-full z-20 mt-2 w-64 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift max-sm:end-0"
      >
        <button
          v-for="action in more"
          :key="action.key"
          type="button"
          class="flex min-h-tap w-full items-center gap-3 px-4 text-start text-sm font-medium transition duration-200 ease-rpos hover:bg-background disabled:cursor-not-allowed disabled:opacity-40"
          :class="action.destructive ? 'text-danger' : ''"
          :disabled="action.disabled"
          @click="choose(action)"
        >
          <AppIcon
            :name="action.icon"
            :size="20"
          />
          {{ t(action.label) }}
        </button>
      </div>
    </div>
  </div>
</template>
