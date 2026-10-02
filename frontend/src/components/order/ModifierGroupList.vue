<script setup lang="ts">
import type { ModifierGroup } from "@/api/modifiers";
import { formatNumber, pick, t } from "@/i18n";

/**
 * The groups of a popup, each with its options as buttons (FR-4.4).
 *
 * One list for the dish's popup, the combo's, and a combo item's own add-ons
 * opened over it (D-292): the same question drawn the same way everywhere.
 * What is chosen is the caller's, so the rules about choosing live in one
 * place.
 */
defineProps<{ groups: ModifierGroup[]; chosen: Record<string, string[]> }>();
const emit = defineEmits<{ toggle: [group: ModifierGroup, title: string] }>();
</script>

<template>
  <section
    v-for="group in groups"
    :key="group.name"
    class="mb-4"
  >
    <h3 class="mb-2 text-sm font-medium">
      {{ pick(group.title_ar, group.title) }}
      <span
        v-if="group.is_required"
        class="text-danger"
      >*</span>
      <span class="text-muted">
        ({{ group.selection_type === "single" ? t("mod.single") : t("mod.multi") }})
      </span>
    </h3>

    <div class="flex flex-wrap gap-2">
      <button
        v-for="option in group.options"
        :key="option.title"
        type="button"
        class="min-h-tap rounded-rpos border px-4 text-sm"
        :class="
          (chosen[group.name] ?? []).includes(option.title)
            ? 'border-primary bg-primary text-primary-contrast'
            : 'border-line bg-surface'
        "
        :aria-pressed="(chosen[group.name] ?? []).includes(option.title)"
        @click="emit('toggle', group, option.title)"
      >
        {{ pick(option.title_ar, option.label ?? option.title) }}
        <span
          v-if="option.price_amount"
          class="rpos-numeric text-xs"
        >
          {{ option.price_effect === "subtract" ? "−" : "+" }}{{ formatNumber(option.price_amount, 2) }}
        </span>
      </button>
    </div>
    <slot :group="group" />
  </section>
</template>
