<script setup lang="ts">
import { ref } from "vue";

import AppIcon, { type IconName } from "@/components/AppIcon.vue";
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

function choose(action: OrderAction): void {
  if (action.disabled) return;
  menuOpen.value = false;
  emit("select", action);
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2.5">
    <button
      v-for="action in actions"
      :key="action.key"
      type="button"
      class="flex min-h-[3.375rem] items-center gap-2.5 whitespace-nowrap rounded-rpos px-[22px] text-sm font-medium transition duration-200 ease-rpos disabled:cursor-not-allowed disabled:opacity-40"
      :class="
        action.primary
          ? 'bg-primary text-primary-contrast shadow-primary disabled:shadow-none'
          : 'border border-line-strong bg-surface hover:border-primary'
      "
      :disabled="action.disabled"
      @click="choose(action)"
    >
      <AppIcon
        :name="action.icon"
        :size="19"
        class="opacity-85"
      />
      {{ t(action.label) }}
    </button>

    <div
      v-if="more.length"
      class="relative"
    >
      <button
        type="button"
        class="flex min-h-[3.375rem] items-center gap-2.5 whitespace-nowrap rounded-rpos border border-line-strong bg-surface px-[22px] text-sm font-medium transition duration-200 ease-rpos hover:border-primary"
        :aria-expanded="menuOpen"
        @click="menuOpen = !menuOpen"
      >
        <AppIcon
          name="moreHorizontal"
          :size="19"
          class="opacity-85"
        />
        {{ t("order.more") }}
      </button>

      <div
        v-if="menuOpen"
        class="absolute top-full z-20 mt-2 w-64 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift"
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
