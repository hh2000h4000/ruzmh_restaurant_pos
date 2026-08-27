<script setup lang="ts">
import { computed, ref } from "vue";

// `pick` is already this component's "add this item" handler, so the i18n
// helper comes in under a name that says what it does here.
import AppIcon from "@/components/AppIcon.vue";
import { formatNumber, pick as localized, t } from "@/i18n";
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
const emit = defineEmits<{ pick: [item: CatalogItem, qty: number] }>();

const session = useSessionStore();

const search = ref("");
const activeGroup = ref<string | null>(null);

/**
 * How many of the next item to add.
 *
 * Six of the same drink is one tap on "6" and one on the drink, not six taps
 * on the drink — the difference between a queue that moves and one that does
 * not. It falls back to 1 after every add, because a quantity left standing is
 * how the next customer gets six of something.
 */
const qty = ref(1);
const MAX_QTY = 99;

function bumpQty(by: number): void {
  qty.value = Math.min(MAX_QTY, Math.max(1, qty.value + by));
}

/** Which price list this order sells from, when it is not the terminal's. */
const priceListName = computed(() => props.orderType?.selling_price_list ?? null);

/** Where in the menu the cashier is, so a drilled-in group is not a dead end. */
const breadcrumb = computed(() => {
  if (search.value.trim()) return t("picker.search");
  if (!activeGroup.value) return t("picker.allItems");

  const group = session.data?.item_groups.find((row) => row.name === activeGroup.value);
  return group?.item_group_name ?? activeGroup.value;
});

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
  if (!item || priceOf(item) === null || props.disabled) return;

  emit("pick", item, qty.value);
  qty.value = 1;
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

  // `goto_screen` needs an endpoint that fetches another layout — the session
  // carries only the one assigned to this terminal. `action` buttons need the
  // discount and split flows. Both arrive with the layout designer in Phase 4,
  // so those buttons render disabled rather than swallowing a tap.
}

function isUsable(button: LayoutButton): boolean {
  return button.button_type === "item" || button.button_type === "item_group";
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
  const configured = localized(button.display_text_ar, button.display_text);
  if (configured) return configured;

  if (button.button_type === "item") {
    const item = itemFor(button.item);
    return item ? itemName(item) : (button.item ?? "");
  }
  return button.item_group ?? button.action_type ?? "";
}

function itemName(item: CatalogItem): string {
  return localized(item.pos_display_name_ar, item.item_name);
}

/** FR-1.6 — an order type may sell from its own price list. */
function priceOf(item: CatalogItem): number | null {
  return session.priceOf(item, props.orderType);
}
</script>

<template>
  <!-- A search field over one scrolling grid: whichever grid the state calls
       for, it is the only thing on this panel that moves. -->
  <div class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-3">
    <div class="flex flex-col gap-3">
      <div class="flex flex-wrap items-center gap-3">
        <label
          class="sr-only"
          for="item-search"
        >{{ t("picker.search") }}</label>
        <div class="relative min-w-0 flex-1">
          <span
            class="pointer-events-none absolute inset-y-0 start-4 grid place-items-center text-muted"
          >
            <AppIcon
              name="search"
              :size="20"
            />
          </span>
          <input
            id="item-search"
            v-model="search"
            type="search"
            :placeholder="t('picker.search')"
            class="h-[52px] w-full rounded-full bg-background ps-12 pe-4 text-base outline-none transition duration-200 ease-rpos focus:bg-surface focus:ring-2 focus:ring-primary/30"
          >
        </div>

        <!-- Set the quantity, then tap the item. -->
        <div class="flex h-[52px] shrink-0 items-center gap-1 rounded-full bg-background px-2">
          <span class="ps-2 text-sm font-medium text-muted">{{ t("picker.qty") }}</span>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-surface disabled:opacity-40"
            :disabled="qty <= 1"
            :aria-label="t('picker.qtyLess')"
            @click="bumpQty(-1)"
          >
            <AppIcon
              name="minus"
              :size="20"
            />
          </button>
          <span
            class="rpos-numeric w-8 text-center text-lg font-bold"
            aria-live="polite"
          >{{ formatNumber(qty) }}</span>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-full text-muted transition duration-200 ease-rpos hover:bg-surface disabled:opacity-40"
            :disabled="qty >= 99"
            :aria-label="t('picker.qtyMore')"
            @click="bumpQty(1)"
          >
            <AppIcon
              name="plus"
              :size="20"
            />
          </button>
        </div>
      </div>

      <!-- Where you are, and which prices you are seeing (FR-1.6). -->
      <p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
        <span>{{ breadcrumb }}</span>
        <template v-if="priceListName">
          <span aria-hidden="true">·</span>
          <span>{{ t("picker.priceList") }}: {{ priceListName }}</span>
        </template>
      </p>
    </div>

    <!-- Search wins over whatever else is on screen. -->
    <div
      v-if="search.trim()"
      class="grid auto-rows-min grid-cols-2 gap-2.5 overflow-y-auto sm:grid-cols-3 2xl:grid-cols-4"
    >
      <button
        v-for="item in searchResults"
        :key="item.item_code"
        type="button"
        class="flex min-h-[5.5rem] flex-col justify-between rounded-rpos border border-line bg-surface p-3 text-start transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-card disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="priceOf(item) === null || disabled"
        @click="pick(item)"
      >
        <span class="line-clamp-2 font-semibold leading-snug">{{ itemName(item) }}</span>
        <span
          v-if="priceOf(item) !== null"
          class="rpos-numeric font-bold text-primary"
        >{{ formatNumber(priceOf(item)!, 2) }}</span>
        <span
          v-else
          class="text-sm text-danger"
        >{{ t("picker.noPrice") }}</span>
      </button>
      <p
        v-if="!searchResults.length"
        class="col-span-full p-6 text-center text-muted"
      >
        {{ t("picker.noResults") }}
      </p>
    </div>

    <!-- A group was opened from a layout button or the fallback browser. -->
    <div
      v-else-if="activeGroup"
      class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2.5"
    >
      <button
        type="button"
        class="flex min-h-tap items-center gap-1.5 self-start rounded-rpos px-3 text-sm font-medium text-primary transition duration-200 ease-rpos hover:bg-primary/10"
        @click="activeGroup = null"
      >
        <AppIcon
          name="back"
          class="rpos-flip"
          :size="18"
        />
        {{ t("action.back") }}
      </button>
      <div class="grid auto-rows-min grid-cols-2 gap-2.5 overflow-y-auto sm:grid-cols-3 2xl:grid-cols-4">
        <button
          v-for="item in groupItems"
          :key="item.item_code"
          type="button"
          class="flex min-h-[5.5rem] flex-col justify-between rounded-rpos border border-line bg-surface p-3 text-start transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-card disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="priceOf(item) === null || disabled"
          @click="pick(item)"
        >
          <span class="line-clamp-2 font-semibold leading-snug">{{ itemName(item) }}</span>
          <span
            v-if="priceOf(item) !== null"
            class="rpos-numeric font-bold text-primary"
          >{{ formatNumber(priceOf(item)!, 2) }}</span>
          <span
            v-else
            class="text-sm text-danger"
          >{{ t("picker.noPrice") }}</span>
        </button>
      </div>
    </div>

    <!-- The configured layout (FR-3.1). Its colours come from the designer, so
         they are inline styles rather than tokens. -->
    <div
      v-else-if="layout"
      class="grid gap-2.5 overflow-y-auto"
      :style="{
        gridTemplateColumns: `repeat(${layout.grid_columns}, minmax(0, 1fr))`,
        gridAutoRows: 'minmax(5.5rem, auto)',
      }"
    >
      <button
        v-for="button in layout.buttons"
        :key="button.idx"
        type="button"
        class="flex items-center justify-center rounded-rpos border border-line bg-surface p-3 text-center font-semibold transition duration-200 ease-rpos hover:-translate-y-px hover:shadow-card disabled:cursor-not-allowed disabled:opacity-40"
        :style="buttonStyle(button)"
        :disabled="disabled || !isUsable(button)"
        @click="onLayoutButton(button)"
      >
        {{ label(button) }}
      </button>
    </div>

    <!-- No layout configured: browse by group. -->
    <div
      v-else
      class="grid auto-rows-min grid-cols-2 gap-2.5 overflow-y-auto sm:grid-cols-3 2xl:grid-cols-4"
    >
      <button
        v-for="group in groups"
        :key="group.name"
        type="button"
        class="flex min-h-[5.5rem] items-center justify-center rounded-rpos border border-line bg-surface p-3 text-center font-semibold transition duration-200 ease-rpos hover:-translate-y-px hover:border-primary/40 hover:shadow-card"
        @click="activeGroup = group.name"
      >
        {{ group.item_group_name }}
      </button>
      <p
        v-if="!groups.length"
        class="col-span-full p-6 text-center text-muted"
      >
        {{ t("picker.empty") }}
      </p>
    </div>
  </div>
</template>
