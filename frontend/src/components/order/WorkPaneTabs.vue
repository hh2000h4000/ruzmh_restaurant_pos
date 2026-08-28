<script setup lang="ts">
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { formatNumber, t, type MessageKey } from "@/i18n";

/**
 * What the working column is showing right now.
 *
 * The order screen keeps the bill on the side and swaps only this column
 * (D-039), so a cashier can look at the floor without abandoning the order in
 * front of them. A tab strip rather than a bottom bar: it sits directly over
 * the pane it controls, and the bottom bar on the till screen means actions,
 * not navigation — two bars that look alike and behave differently is worse
 * than one bar in the right place.
 */
export interface WorkPane {
  key: string;
  label: MessageKey;
  icon: IconName;
  /** Shown as a badge; omitted when there is nothing to count. */
  count?: number;
}

defineProps<{ panes: WorkPane[] }>();
const active = defineModel<string>("active", { required: true });
</script>

<template>
  <div
    class="flex rounded-rpos bg-surface p-1 shadow-card"
    role="tablist"
  >
    <button
      v-for="pane in panes"
      :key="pane.key"
      type="button"
      role="tab"
      class="flex min-h-tap items-center gap-2 rounded-[0.75rem] px-4 text-sm font-semibold transition duration-200 ease-rpos"
      :class="
        active === pane.key ? 'bg-primary text-primary-contrast shadow-card' : 'text-muted hover:bg-background'
      "
      :aria-selected="active === pane.key"
      @click="active = pane.key"
    >
      <AppIcon
        :name="pane.icon"
        :size="20"
      />
      {{ t(pane.label) }}

      <span
        v-if="pane.count"
        class="rpos-numeric grid h-6 min-w-[1.5rem] place-items-center rounded-full px-1.5 text-xs font-bold"
        :class="active === pane.key ? 'bg-primary-contrast/20' : 'bg-primary/10 text-primary'"
      >{{ formatNumber(pane.count) }}</span>
    </button>
  </div>
</template>
