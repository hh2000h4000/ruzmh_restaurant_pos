<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { getModifierGroups, type ModifierGroup } from "@/api/modifiers";
import type { ModifierChoice } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, pick, t } from "@/i18n";
import type { CatalogItem } from "@/types/session";

/**
 * Modifier selection (FR-4.4).
 *
 * Required groups must be resolved before the item can be added. Prices shown
 * here are indicative: the backend prices every option again from
 * `POS Modifier Option`, because a client-supplied amount would make extras
 * free (D-020).
 */
const props = defineProps<{ item: CatalogItem | null }>();
const emit = defineEmits<{
  confirm: [payload: { modifiers: ModifierChoice[]; notes: string }];
  cancel: [];
}>();

const groups = ref<ModifierGroup[]>([]);
const chosen = ref<Record<string, string[]>>({});
const notes = ref("");
const loading = ref(false);
const failure = ref<string | null>(null);

watch(
  () => props.item,
  async (item) => {
    groups.value = [];
    chosen.value = {};
    notes.value = "";
    failure.value = null;

    if (!item?.modifier_groups.length) return;

    loading.value = true;
    try {
      groups.value = await getModifierGroups(item.modifier_groups);
      for (const group of groups.value) {
        chosen.value[group.name] = group.options
          .filter((option) => option.is_default)
          .map((option) => option.title);
      }
    } catch (cause) {
      failure.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

function toggle(group: ModifierGroup, title: string): void {
  const current = chosen.value[group.name] ?? [];

  if (group.selection_type === "single") {
    chosen.value[group.name] = current.includes(title) ? [] : [title];
    return;
  }

  if (current.includes(title)) {
    chosen.value[group.name] = current.filter((value) => value !== title);
    return;
  }

  const max = group.max_selections;
  if (max && current.length >= max) return;

  chosen.value[group.name] = [...current, title];
}

function isChosen(group: ModifierGroup, title: string): boolean {
  return (chosen.value[group.name] ?? []).includes(title);
}

/** Which required groups still have no answer — the reason Confirm is disabled. */
const unresolved = computed(() =>
  groups.value.filter((group) => {
    const count = (chosen.value[group.name] ?? []).length;
    if (group.is_required && count === 0) return true;
    return group.selection_type === "multiple" && count < (group.min_selections || 0);
  }),
);

const priceDelta = computed(() => {
  let delta = 0;
  for (const group of groups.value) {
    for (const title of chosen.value[group.name] ?? []) {
      const option = group.options.find((candidate) => candidate.title === title);
      if (!option) continue;
      if (option.price_effect === "add" || option.price_effect === "replace") {
        delta += option.price_amount;
      } else if (option.price_effect === "subtract") {
        delta -= option.price_amount;
      }
    }
  }
  return delta;
});

function confirm(): void {
  if (unresolved.value.length) return;

  const modifiers: ModifierChoice[] = [];
  for (const group of groups.value) {
    for (const option of chosen.value[group.name] ?? []) {
      modifiers.push({ group: group.name, option });
    }
  }

  emit("confirm", { modifiers, notes: notes.value.trim() });
}
</script>

<template>
  <BaseDialog
    :open="Boolean(item)"
    :title="item ? pick(item.pos_display_name_ar, item.item_name) : ''"
    :dismissible="true"
    @close="emit('cancel')"
  >
    <p
      v-if="loading"
      class="py-6 text-center text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <p
      v-else-if="failure"
      role="alert"
      class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <template v-else>
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
              isChosen(group, option.title)
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line bg-surface'
            "
            :aria-pressed="isChosen(group, option.title)"
            @click="toggle(group, option.title)"
          >
            {{ pick(option.title_ar, option.title) }}
            <span
              v-if="option.price_amount"
              class="rpos-numeric text-xs"
            >
              {{ option.price_effect === "subtract" ? "−" : "+" }}{{ formatNumber(option.price_amount, 2) }}
            </span>
          </button>
        </div>
      </section>

      <label
        for="line-notes"
        class="mb-1.5 block text-sm font-medium"
      >{{ t("mod.note") }}</label>
      <textarea
        id="line-notes"
        v-model="notes"
        rows="2"
        class="mb-4 w-full rounded-rpos border border-line bg-background p-2 text-base focus:outline-none focus:ring-2 focus:ring-primary"
      />

      <p
        v-if="priceDelta"
        class="rpos-numeric mb-3 text-sm text-muted"
      >
        {{ t("mod.priceDelta") }} {{ formatNumber(priceDelta, 2) }}
      </p>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line px-4"
          @click="emit('cancel')"
        >
          {{ t("action.cancel") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary px-4 font-medium text-primary-contrast disabled:opacity-60"
          :disabled="unresolved.length > 0"
          @click="confirm"
        >
          {{ t("mod.add") }}
        </button>
      </div>

      <p
        v-if="unresolved.length"
        class="mt-3 text-sm text-danger"
      >
        {{ t("mod.choose") }}
        {{
          unresolved.map((group) => pick(group.title_ar, group.title)).join(t("common.listSeparator"))
        }}
      </p>
    </template>
  </BaseDialog>
</template>
