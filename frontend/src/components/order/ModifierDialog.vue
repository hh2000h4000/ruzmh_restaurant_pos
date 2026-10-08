<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ModifierGroup } from "@/api/modifiers";
import type { ModifierChoice } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import ModifierGroupList from "@/components/order/ModifierGroupList.vue";
import NoteEditor from "@/components/order/NoteEditor.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useStockStore } from "@/stores/stock";
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

const session = useSessionStore();
const stock = useStockStore();

const groups = ref<ModifierGroup[]>([]);
const chosen = ref<Record<string, string[]>>({});
const notes = ref("");
const loading = ref(false);
const failure = ref<string | null>(null);
/** The combo item whose add-ons are open over the combo (D-292). */
const editing = ref<string | null>(null);

/**
 * D-076 — read from the session, not fetched.
 *
 * This used to ask the server every time it opened, which made the popup wait a
 * round trip in front of a customer and made "extra cheese" **impossible during
 * an outage**. The groups ship with the menu now; there are far fewer of them
 * than there are items, and the items were already there.
 */
watch(
  () => props.item,
  (item) => {
    groups.value = [];
    chosen.value = {};
    notes.value = "";
    failure.value = null;
    editing.value = null;

    if (!item?.modifier_groups.length) return;

    const wanted = new Set(item.modifier_groups);
    groups.value = (session.data?.modifier_groups ?? []).filter((group) => wanted.has(group.name));

    if (groups.value.length !== item.modifier_groups.length) {
      // The menu names a group this terminal did not receive — a cache written
      // before the group existed, or a menu edited since. Saying so beats
      // showing half the options as though they were all of them.
      failure.value = t("mod.missing");
      return;
    }

    for (const group of groups.value) {
      chosen.value[group.name] = group.options
        // A default that is sold out is not chosen for the cashier (`D-336`):
        // its button is disabled, so they could not take it off again.
        .filter((option) => option.is_default && !stock.of(option.sells_item ?? "")?.blocked)
        .map((option) => option.title);
    }
  },
  { immediate: true },
);

/**
 * The groups asked right now: a combo item's own groups only while that item
 * is the one chosen (D-289). A hidden group is neither required nor sent.
 */
const shown = computed(() =>
  groups.value.filter(
    (group) => !group.when || (chosen.value[group.when.group] ?? []).includes(group.when.option),
  ),
);

function toggle(group: ModifierGroup, title: string): void {
  const current = chosen.value[group.name] ?? [];

  if (group.selection_type === "single") {
    chosen.value[group.name] = current.includes(title) ? [] : [title];
  } else if (current.includes(title)) {
    chosen.value[group.name] = current.filter((value) => value !== title);
  } else {
    const max = group.max_selections;
    if (max && current.length >= max) return;
    chosen.value[group.name] = [...current, title];
  }

  // Toast asks a nested group the moment its option is picked (D-292): an item
  // chosen in the combo with a question it cannot go without opens it at once.
  if (!group.part && (chosen.value[group.name] ?? []).includes(title)) {
    if (unresolvedFor(title).length) editing.value = title;
  }
}

/**
 * A combo item's own add-ons are asked over the combo, not under it (D-292).
 *
 * Laid out under its choices they ran the popup off the screen, and the
 * cashier scrolled past questions about items nobody had picked. Square adds
 * the combo and offers «Modify» per item with a summary; Toast prompts a nested
 * group as soon as its option is picked. So: the combo shows its choices, each
 * chosen item a line of what was picked on it and a button to change it, and
 * a required question opens by itself.
 */
const topGroups = computed(() => shown.value.filter((group) => !group.part));

function addOnsOf(item: string): ModifierGroup[] {
  return shown.value.filter((group) => group.part?.item === item);
}

/** The chosen items of a combo choice that have add-ons of their own. */
function partsUnder(group: ModifierGroup): string[] {
  return (chosen.value[group.name] ?? []).filter((title) => addOnsOf(title).length);
}

/** The items always in the combo that have add-ons of their own. */
const fixedParts = computed(() => [
  ...new Set(shown.value.filter((group) => group.part && !group.when).map((group) => group.part!.item)),
]);

function partName(item: string): string {
  const part = groups.value.find((group) => group.part?.item === item)?.part;
  return part ? pick(part.title_ar, part.title) : item;
}

/** What was picked on one combo item, as a line under it. */
function summary(item: string): string {
  return addOnsOf(item)
    .flatMap((group) =>
      (chosen.value[group.name] ?? []).map((title) => {
        const option = group.options.find((candidate) => candidate.title === title);
        return option ? pick(option.title_ar, option.label ?? option.title) : title;
      }),
    )
    .join(t("common.listSeparator"));
}

function unresolvedFor(item: string): ModifierGroup[] {
  return unresolved.value.filter((group) => group.part?.item === item);
}

/** Which required groups still have no answer — the reason Confirm is disabled. */
const unresolved = computed(() =>
  shown.value.filter((group) => {
    const count = (chosen.value[group.name] ?? []).length;
    if (group.is_required && count === 0) return true;
    return group.selection_type === "multiple" && count < (group.min_selections || 0);
  }),
);

const priceDelta = computed(() => {
  let delta = 0;
  for (const group of shown.value) {
    for (const title of chosen.value[group.name] ?? []) {
      const option = group.options.find((candidate) => candidate.title === title);
      if (!option) continue;
      if (option.price_effect === "add") {
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
  for (const group of shown.value) {
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
      <ModifierGroupList
        :groups="topGroups"
        :chosen="chosen"
        @toggle="toggle"
      >
        <template #default="{ group }">
          <p
            v-for="part in partsUnder(group)"
            :key="part"
            class="mt-2 flex items-center gap-2 text-sm"
            data-combo-part-summary
          >
            <span class="font-medium">{{ partName(part) }}</span>
            <span
              v-if="summary(part)"
              class="truncate text-muted"
            >· {{ summary(part) }}</span>
            <button
              type="button"
              class="min-h-tap rounded-rpos border border-line px-3 text-sm"
              :class="unresolvedFor(part).length ? 'border-danger text-danger' : ''"
              data-combo-part-edit
              @click="editing = part"
            >
              {{ t("mod.extras") }}
            </button>
          </p>
        </template>
      </ModifierGroupList>

      <section
        v-if="fixedParts.length"
        class="mb-4"
      >
        <h3 class="mb-2 text-sm font-medium">
          {{ t("mod.withMeal") }}
        </h3>
        <p
          v-for="part in fixedParts"
          :key="part"
          class="mt-2 flex items-center gap-2 text-sm"
          data-combo-part-summary
        >
          <span class="font-medium">{{ partName(part) }}</span>
          <span
            v-if="summary(part)"
            class="truncate text-muted"
          >· {{ summary(part) }}</span>
          <button
            type="button"
            class="min-h-tap rounded-rpos border border-line px-3 text-sm"
            :class="unresolvedFor(part).length ? 'border-danger text-danger' : ''"
            data-combo-part-edit
            @click="editing = part"
          >
            {{ t("mod.extras") }}
          </button>
        </p>
      </section>

      <p class="mb-1.5 text-sm font-medium">
        {{ t("mod.note") }}
      </p>
      <!-- FR-2.9 — this note reaches the one station that cooks this dish. -->
      <NoteEditor
        v-model="notes"
        class="mb-4"
        scope="item"
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
          unresolved
            .map((group) => (group.part ? partName(group.part.item) : pick(group.title_ar, group.title)))
            .join(t("common.listSeparator"))
        }}
      </p>
    </template>
  </BaseDialog>

  <!-- A combo item's add-ons, over the combo (D-292). -->
  <BaseDialog
    :open="editing !== null"
    :title="editing ? partName(editing) : ''"
    @close="editing = null"
  >
    <ModifierGroupList
      v-if="editing"
      :groups="addOnsOf(editing)"
      :chosen="chosen"
      @toggle="toggle"
    />
    <button
      type="button"
      class="min-h-tap w-full rounded-rpos bg-primary px-4 font-medium text-primary-contrast disabled:opacity-60"
      :disabled="editing !== null && unresolvedFor(editing).length > 0"
      data-combo-part-done
      @click="editing = null"
    >
      {{ t("mod.done") }}
    </button>
  </BaseDialog>
</template>
