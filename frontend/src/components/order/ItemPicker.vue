<script setup lang="ts">
import { computed, ref } from "vue";

import { useSessionStore } from "@/stores/session";
import type { CatalogItem, LayoutButton, OrderType } from "@/types/session";

/**
 * The item side of the order screen (Screen 3).
 *
 * Renders the configured screen layout when there is one (FR-3.1–3.3) and falls
 * back to browsing item groups when there is not — a restaurant that has not
 * built a layout yet still needs to take orders.
 *
 * Search is always available: on a long menu it beats any grid (Screen 3).
 */
const props = defineProps<{ orderType: OrderType | null; disabled?: boolean }>();
const emit = defineEmits<{ pick: [item: CatalogItem] }>();

const session = useSessionStore();

const search = ref("");
const activeGroup = ref<string | null>(null);
/** Layout navigation stack, so `goto_screen` can be backed out of (FR-3.3). */
const layoutStack = ref<string[]>([]);

const available = computed(() => session.visibleItems(props.orderType));

const layout = computed(() => {
  const configured = session.data?.screen_layout;
  if (!configured?.buttons.length) return null;
  return configured;
});

const searchResults = computed(() => {
  const term = search.value.trim().toLowerCase();
  if (!term) return [];

  return available.value
    .filter(
      (item) =>
        item.display_name.toLowerCase().includes(term) ||
        item.item_name.toLowerCase().includes(term) ||
        item.item_code.toLowerCase().includes(term),
    )
    .slice(0, 60);
});

const groups = computed(() => {
  const used = new Set(available.value.map((item) => item.item_group));
  return (session.data?.item_groups ?? []).filter((group) => used.has(group.name));
});

const groupItems = computed(() =>
  activeGroup.value ? available.value.filter((item) => item.item_group === activeGroup.value) : [],
);

/** A button is unusable if its item has no price (D-020). */
function itemFor(code: string | null): CatalogItem | undefined {
  return code ? session.itemsByCode.get(code) : undefined;
}

function pick(item: CatalogItem | undefined): void {
  if (!item || item.rate === null || props.disabled) return;
  emit("pick", item);
}

function onLayoutButton(button: LayoutButton): void {
  if (button.button_type === "item") {
    pick(itemFor(button.item));
    return;
  }

  if (button.button_type === "item_group") {
    activeGroup.value = button.item_group;
    return;
  }

  if (button.button_type === "goto_screen" && button.goto_screen) {
    layoutStack.value.push(button.goto_screen);
  }
  // `action` buttons are wired in Phase 4 with the discount and split flows.
}

function gridStyle(button: LayoutButton): Record<string, string> {
  return {
    gridColumn: `${button.col_start} / span ${button.col_span}`,
    gridRow: `${button.row_start} / span ${button.row_span}`,
  };
}

/**
 * Layout buttons carry their own colours from the designer (05 §9), so these
 * are configuration rather than hardcoded values — the one place a colour
 * legitimately arrives as data.
 */
function buttonStyle(button: LayoutButton): Record<string, string> {
  const style: Record<string, string> = gridStyle(button);
  if (button.bg_color) style.backgroundColor = button.bg_color;
  if (button.text_color) style.color = button.text_color;
  if (button.font_size) style.fontSize = `${button.font_size}px`;
  return style;
}

function label(button: LayoutButton): string {
  if (button.display_text_ar) return button.display_text_ar;
  if (button.display_text) return button.display_text;
  if (button.button_type === "item") return itemFor(button.item)?.display_name ?? button.item ?? "";
  return button.item_group ?? button.action_type ?? "";
}
</script>

<template>
  <div class="flex h-full flex-col gap-3">
    <label class="sr-only" for="item-search">بحث عن صنف</label>
    <input
      id="item-search"
      v-model="search"
      type="search"
      placeholder="🔍 بحث عن صنف"
      class="min-h-tap w-full rounded-rpos border border-line bg-surface px-3 text-base focus:outline-none focus:ring-2 focus:ring-primary"
    >

    <!-- Search wins over whatever else is on screen. -->
    <div
      v-if="search.trim()"
      class="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-3"
    >
      <button
        v-for="item in searchResults"
        :key="item.item_code"
        type="button"
        class="flex min-h-tap flex-col items-start rounded-rpos bg-surface p-3 text-start shadow-sm disabled:opacity-50"
        :disabled="item.rate === null || disabled"
        @click="pick(item)"
      >
        <span class="text-sm font-medium">{{ item.display_name }}</span>
        <span v-if="item.rate !== null" class="rpos-numeric text-xs text-muted">
          {{ item.rate.toFixed(2) }}
        </span>
        <span v-else class="text-xs text-danger">بلا سعر</span>
      </button>
      <p v-if="!searchResults.length" class="col-span-full p-4 text-center text-muted">
        لا نتائج.
      </p>
    </div>

    <!-- A group was opened from a layout button or the fallback browser. -->
    <div v-else-if="activeGroup" class="flex flex-1 flex-col gap-2 overflow-hidden">
      <button
        type="button"
        class="self-start rounded-rpos px-3 text-sm text-primary"
        @click="activeGroup = null"
      >
        ← رجوع
      </button>
      <div class="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-3">
        <button
          v-for="item in groupItems"
          :key="item.item_code"
          type="button"
          class="flex min-h-[5rem] flex-col items-start rounded-rpos bg-surface p-3 text-start shadow-sm disabled:opacity-50"
          :disabled="item.rate === null || disabled"
          @click="pick(item)"
        >
          <span class="text-sm font-medium">{{ item.display_name }}</span>
          <span v-if="item.rate !== null" class="rpos-numeric text-xs text-muted">
            {{ item.rate.toFixed(2) }}
          </span>
          <span v-else class="text-xs text-danger">بلا سعر</span>
        </button>
      </div>
    </div>

    <!-- The configured layout (FR-3.1). -->
    <div
      v-else-if="layout"
      class="grid flex-1 gap-2 overflow-y-auto"
      :style="{
        gridTemplateColumns: `repeat(${layout.grid_columns}, minmax(0, 1fr))`,
        gridAutoRows: 'minmax(4.5rem, auto)',
      }"
    >
      <button
        v-for="button in layout.buttons"
        :key="button.idx"
        type="button"
        class="flex items-center justify-center rounded-rpos bg-surface p-2 text-center text-sm font-medium shadow-sm disabled:opacity-50"
        :style="buttonStyle(button)"
        :disabled="disabled"
        @click="onLayoutButton(button)"
      >
        {{ label(button) }}
      </button>
    </div>

    <!-- No layout configured: browse by group. -->
    <div v-else class="grid flex-1 auto-rows-min grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-3">
      <button
        v-for="group in groups"
        :key="group.name"
        type="button"
        class="min-h-[5rem] rounded-rpos bg-surface p-3 text-sm font-medium shadow-sm"
        @click="activeGroup = group.name"
      >
        {{ group.item_group_name }}
      </button>
      <p v-if="!groups.length" class="col-span-full p-4 text-center text-muted">
        لا توجد أصناف متاحة.
      </p>
    </div>
  </div>
</template>
