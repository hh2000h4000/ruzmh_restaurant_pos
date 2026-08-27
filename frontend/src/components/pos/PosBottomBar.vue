<script setup lang="ts">
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { t, type MessageKey } from "@/i18n";

/**
 * The bar along the bottom: 70px buttons, icon over label.
 *
 * **Navigation only.** No button here acts on a selected order. A control that
 * acts on "the highlighted card" needs a selection mode, and at a busy till
 * that is how a refund lands on the wrong bill (D-033). Order actions live on
 * the order screen, where the order is unambiguous and every action is
 * permission-checked.
 *
 * The buttons are data, so a screen that does not exist yet is `disabled: true`
 * rather than a link to an empty page.
 */
export interface BottomAction {
  key: string;
  label: MessageKey;
  icon: IconName;
  /** A Tailwind text-colour class; the tint is derived from it. */
  tone: string;
  disabled?: boolean;
}

defineProps<{ actions: BottomAction[] }>();
defineEmits<{ select: [action: BottomAction] }>();
</script>

<template>
  <nav
    class="flex shrink-0 items-center gap-3 border-t border-line bg-surface px-5 py-3 shadow-bar"
  >
    <button
      v-for="action in actions"
      :key="action.key"
      type="button"
      class="flex h-[70px] flex-1 flex-col items-center justify-center gap-1 rounded-rpos text-sm font-semibold transition duration-200 ease-rpos disabled:cursor-not-allowed disabled:opacity-40"
      :class="action.tone"
      :disabled="action.disabled"
      :title="action.disabled ? t('common.soon') : undefined"
      @click="$emit('select', action)"
    >
      <AppIcon
        :name="action.icon"
        :size="24"
      />
      {{ t(action.label) }}
    </button>
  </nav>
</template>
