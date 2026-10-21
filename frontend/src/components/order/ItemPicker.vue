<script setup lang="ts">
import { computed, ref } from "vue";

// `pick` is already this component's "add this item" handler, so the i18n
// helper comes in under a name that says what it does here.
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import MenuTile from "@/components/order/MenuTile.vue";
import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import { useScanner } from "@/composables/useScanner";
import { formatNumber, pick as localized, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useStockStore } from "@/stores/stock";
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
const props = defineProps<{
  orderType: OrderType | null;
  disabled?: boolean;
  /**
   * Marking what is finished for today (`D-322`): a tap marks the item, or
   * brings it back, instead of adding it to the bill.
   *
   * **The menu itself is the list.** A cashier already knows where the soup is
   * on this screen; a second list of every item, with a search box on a till
   * that has no keyboard, would be a second thing to learn. Toast marks its
   * items the same way — on the buttons, in an edit mode.
   */
  marking?: boolean;
}>();
const emit = defineEmits<{
  pick: [item: CatalogItem, qty: number, rate?: number];
  failed: [cause: unknown];
  done: [];
}>();

const session = useSessionStore();
const stock = useStockStore();

/** What the tile says about stock: nothing, "8 left", or "Sold out" (`D-321`). */
function stockBadge(item: CatalogItem | undefined): string | null {
  const mark = item ? stock.of(item.item_code) : null;
  if (!mark) return null;
  return mark.finished ? t("stock.soldOut") : t("stock.left", { count: formatNumber(mark.left ?? 0) });
}

function stockFinished(item: CatalogItem | undefined): boolean {
  return Boolean(item && stock.of(item.item_code)?.finished);
}

/** The server would refuse it, so the tile does not offer it. */
function stockBlocked(item: CatalogItem | undefined): boolean {
  return Boolean(item && stock.of(item.item_code)?.blocked);
}

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
        item.item_code.toLowerCase().includes(term) ||
        (item.barcodes ?? []).includes(term),
    )
    .slice(0, 60);
});

/**
 * A scanned code adds its item (`D-341`).
 *
 * **Looked up in the menu the till already holds**, not on the server: a scan is
 * the fastest thing a cashier does, and a request per bottle is a queue. The
 * reader is heard two ways — typed into the search box, or anywhere on the
 * screen when no field has the focus — and both end here.
 *
 * A code nobody knows is said out loud. A reader that beeps and adds nothing
 * is a bottle the customer walks out with unpaid.
 */
function scanned(code: string): boolean {
  const wanted = code.trim();
  if (!wanted || props.marking) return false;

  const item = session.itemsByBarcode.get(wanted);
  if (!item || !available.value.includes(item)) {
    emit("failed", new Error(t("picker.unknownBarcode", { code: wanted })));
    return false;
  }

  // A tile that cannot be tapped says why on its face; a scan has no face.
  if (props.disabled) return false;
  if (tileOff(item)) {
    const why = stockBlocked(item) ? t("stock.soldOut") : t("picker.noPrice");
    emit("failed", new Error(`${item.display_name} — ${why}`));
    return false;
  }

  pick(item);
  return true;
}

useScanner(scanned);

/** Enter in the search box: a scanned code, or the one dish the words left. */
function submitSearch(): void {
  const typed = search.value.trim();
  if (!typed) return;

  if (session.itemsByBarcode.has(typed)) {
    if (scanned(typed)) search.value = "";
    return;
  }

  if (searchResults.value.length === 1) {
    pick(searchResults.value[0]);
    search.value = "";
  }
}

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

/** Whether a dish's tile takes a tap — when marking, every dish does. */
function tileOff(item: CatalogItem | undefined): boolean {
  if (props.marking) return !item;
  return (
    !item ||
    (priceOf(item) === null && !item.open_price) ||
    Boolean(props.disabled) ||
    stockBlocked(item)
  );
}

async function toggleFinished(item: CatalogItem): Promise<void> {
  try {
    await stock.mark(item.item_code, !stock.soldOut.has(item.item_code));
  } catch (cause) {
    emit("failed", cause);
  }
}

function pick(item: CatalogItem | undefined): void {
  if (tileOff(item) || !item) return;
  if (props.marking) {
    void toggleFinished(item);
    return;
  }

  // `D-378` — a dish priced at the counter asks for its price first.
  if (item.open_price) {
    pricing.value = item;
    typedPrice.value = "0";
    return;
  }

  emit("pick", item, qty.value);
  qty.value = 1;
}

/** The open-price dish waiting for its price, and what has been typed. */
const pricing = ref<CatalogItem | null>(null);
const typedPrice = ref("0");
const price = computed(() => Number(typedPrice.value) || 0);

function priced(): void {
  const item = pricing.value;
  if (!item || price.value <= 0) return;
  pricing.value = null;
  emit("pick", item, qty.value, price.value);
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

/**
 * How many across a flow layout runs (`D-142`).
 *
 * **The count decides it, because the screen has to hold all of them.** Three
 * across was a number written for a demo with six groups; a restaurant with
 * fifty would have got seventeen rows and a scroll on every order — and a
 * cashier hunting for a category through a scrollbar is the slow till this
 * product exists to replace. The tiles shrink instead, which is what a manager
 * would do by hand and the only thing that *guarantees* the fit: a layout drawn
 * on a grid can always be drawn too big for its screen.
 *
 * The steps are coarse on purpose. A formula would keep changing the shape of
 * the menu as a group is added or removed, and a cashier learns positions by
 * hand — a screen that reflows on every menu edit is one they have to re-read.
 */
const FLOW_COLUMNS = [
  { upTo: 6, columns: 3 },
  { upTo: 12, columns: 4 },
  { upTo: 20, columns: 5 },
  { upTo: 30, columns: 6 },
  { upTo: 42, columns: 7 },
  { upTo: Number.POSITIVE_INFINITY, columns: 8 },
];

/**
 * Where the grid comes from, and when it comes from nowhere (`D-141`).
 *
 * **`flow` is the mode a restaurant should use.** The buttons go in the order
 * the manager dragged them into and the coordinates are ignored, so arranging a
 * menu is dragging rows in a table rather than inventing `col_start = 3`.
 *
 * `grid` is for a screen somebody has deliberately drawn, and it means exactly
 * what its numbers say.
 *
 * **The rows divide the height rather than setting it** in flow: `1fr` shares
 * what the card has, and `minmax` refuses to go under a finger. Past that many
 * buttons it scrolls — the honest end, because tiles below a touch target are
 * not a menu, they are a picture of one.
 *
 * **The count is the most across, not the fewest.** A phone cannot hold five
 * tiles: thirteen buttons on a 360 screen made five columns 46 points wide, and
 * "Desserts" showed as "Des". So a column goes only while each tile keeps
 * `FLOW_MIN_TILE` — the tablet the steps were measured on still gets all of
 * them, and the phone gets fewer, taller rows and a scroll.
 */
const FLOW_MIN_TILE = "6rem";

const layoutStyle = computed<Record<string, string>>(() => {
  if (layout.value?.layout_mode === "grid") {
    const drawn: Record<string, string> = {
      "--columns": String(layout.value.grid_columns),
      gridTemplateColumns: `repeat(${layout.value.grid_columns}, minmax(0, 1fr))`,
      // D-296 — the drawn rows share the card's height, as flow's do. Sized
      // by their tiles instead, a tile's square picture made every row as tall
      // as the column was wide: two buttons on the owner's screen ran the
      // whole height of it.
      gridTemplateRows: `repeat(${layout.value.grid_rows}, minmax(min-content, 1fr))`,
    };
    return drawn;
  }

  const count = layout.value?.buttons.length ?? 0;
  const columns = FLOW_COLUMNS.find((step) => count <= step.upTo)!.columns;

  // A track is a 1/columns share of the row after its gaps (gap-3.5), or
  // FLOW_MIN_TILE when that share is smaller — and auto-fill fits as many of
  // those as the width holds, which is never more than `columns`.
  // A row never goes under the tile's name and price (`min-content` — the
  // picture gives way first, `D-192`), which is always more than a finger. The
  // tap target alone let a short phone, or a phone with an error showing, cut
  // every price off at 48px; now that column scrolls instead.
  return {
    "--columns": String(columns),
    gridTemplateColumns: `repeat(auto-fill, minmax(max(${FLOW_MIN_TILE}, calc((100% - ${columns - 1} * 0.875rem) / ${columns})), 1fr))`,
    gridAutoRows: "minmax(min-content, 1fr)",
  };
});

function gridStyle(button: LayoutButton): Record<string, string> {
  // In flow the button takes the next cell going: a coordinate here would be
  // the thing this mode exists to stop anyone having to think about.
  if (layout.value?.layout_mode !== "grid") return {};

  return {
    gridColumn: `${button.col_start} / span ${button.col_span}`,
    gridRow: `${button.row_start} / span ${button.row_span}`,
  };
}

function groupOf(name: string | null) {
  return name ? session.data?.item_groups.find((row) => row.name === name) : undefined;
}

/** A layout button's dish, when it is one — for its picture and its price. */
function dishOf(button: LayoutButton): CatalogItem | undefined {
  return button.button_type === "item" ? itemFor(button.item) : undefined;
}

/**
 * The picture on a layout button's tile (`D-192`): its own when the layout gave
 * it one, else its dish's or its group's — ERPNext's `image` on each — else the
 * tile draws a placeholder.
 *
 * The button's **colour** goes to the tile's strip and its **text colour** is no
 * longer used: it was chosen for text on a coloured fill, and the tile is white
 * now — white text there would be no text at all.
 */
function imageOf(button: LayoutButton): string | null {
  if (button.image) return button.image;
  if (button.button_type === "item") return dishOf(button)?.image ?? null;
  if (button.button_type === "item_group") return groupOf(button.item_group)?.image ?? null;
  return null;
}

function label(button: LayoutButton): string {
  const configured = localized(button.display_text_ar, button.display_text);
  if (configured) return configured;

  if (button.button_type === "item") {
    const item = itemFor(button.item);
    return item ? itemName(item) : (button.item ?? "");
  }
  // The group's own name, not its record id, when the button carries no text.
  if (button.button_type === "item_group") {
    return groupOf(button.item_group)?.item_group_name ?? button.item_group ?? "";
  }
  return button.action_type ?? "";
}

/** The line under a dish's name: its price, or why it cannot be sold (`D-020`). */
function priceLine(item: CatalogItem): string {
  if (item.open_price) return t("picker.openPrice");
  const price = priceOf(item);
  return price === null ? t("picker.noPrice") : formatNumber(price, 2);
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
  <div class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2">
    <div class="flex flex-col gap-2.5">
      <!-- `D-322` — said for as long as a tap means something else. -->
      <div
        v-if="marking"
        data-marking
        class="flex items-center justify-between gap-3 rounded-rpos border border-danger bg-danger/10 px-4 py-2.5"
      >
        <p class="min-w-0 text-sm font-semibold text-danger">
          {{ t("stock.markingHint") }}
        </p>
        <button
          type="button"
          class="min-h-11 shrink-0 rounded-rpos bg-primary px-5 text-sm font-semibold text-primary-contrast"
          @click="emit('done')"
        >
          {{ t("stock.markingDone") }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2.5">
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
            class="h-14 w-full rounded-lg border border-transparent bg-surface ps-12 pe-4 text-base outline-none transition duration-200 ease-rpos focus:border-primary"
            @keydown.enter.prevent="submitSearch"
          >
        </div>

        <!-- Set the quantity, then tap the item. On a phone the word goes to the
             screen reader only: beside the stepper it left a 360 search field
             room for one letter, and the − 1 + already says what it is. -->
        <div
          class="flex h-14 shrink-0 items-center gap-1 rounded-lg bg-surface px-2"
        >
          <span class="px-2 text-sm text-muted max-sm:sr-only">{{ t("picker.qty") }}</span>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-rpos text-content transition duration-200 ease-rpos hover:bg-background disabled:opacity-40"
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
            class="rpos-numeric min-w-[1.875rem] text-center text-[17px]"
            aria-live="polite"
          >{{ formatNumber(qty) }}</span>
          <button
            type="button"
            class="grid h-11 w-11 place-items-center rounded-rpos text-content transition duration-200 ease-rpos hover:bg-background disabled:opacity-40"
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
    </div>

    <!-- Search wins over whatever else is on screen. -->
    <div
      v-if="search.trim()"
      class="grid auto-rows-min content-start grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
    >
      <MenuTile
        v-for="item in searchResults"
        :key="item.item_code"
        class="min-h-[9.5rem]"
        :label="itemName(item)"
        :image="item.image"
        placeholder="cloche"
        :detail="priceLine(item)"
        :detail-danger="priceOf(item) === null"
        :badge="stockBadge(item)"
        :badge-danger="stockFinished(item)"
        :disabled="tileOff(item)"
        @select="pick(item)"
      />
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
      class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2"
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
      <div class="grid auto-rows-min content-start grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        <MenuTile
          v-for="item in groupItems"
          :key="item.item_code"
          class="min-h-[9.5rem]"
          :label="itemName(item)"
          :image="item.image"
          placeholder="cloche"
          :detail="priceLine(item)"
          :detail-danger="priceOf(item) === null"
          :badge="stockBadge(item)"
          :badge-danger="stockFinished(item)"
          :disabled="tileOff(item)"
          @select="pick(item)"
        />
      </div>
    </div>

    <!--
      The configured layout (FR-3.1). Its colours come from the designer, so
      they are inline styles rather than tokens.

      `content-start` is what keeps a button a button. A grid taller than its
      rows stretches `auto` rows to fill it by default, so six tiles in a screen
      of space became six slabs a third of the pane tall each — and the fewer
      the buttons, the more absurd it looked.
    -->
    <div
      v-else-if="layout"
      class="grid h-full gap-3.5 overflow-y-auto"
      :style="layoutStyle"
    >
      <!-- Flow and a drawn grid alike divide the card's height into rows, so
           every tile is the size its row gives it (D-296). -->
      <MenuTile
        v-for="button in layout.buttons"
        :key="button.idx"
        :style="gridStyle(button)"
        :label="label(button)"
        :image="imageOf(button)"
        :placeholder="button.button_type === 'item' ? 'cloche' : 'grid'"
        :accent="button.bg_color"
        :font-size="button.font_size"
        :detail="dishOf(button) ? priceLine(dishOf(button)!) : null"
        :detail-danger="dishOf(button) ? priceOf(dishOf(button)!) === null : false"
        :badge="stockBadge(dishOf(button))"
        :badge-danger="stockFinished(dishOf(button))"
        :disabled="button.button_type === 'item' ? tileOff(dishOf(button)) : (disabled && !marking) || !isUsable(button)"
        @select="onLayoutButton(button)"
      />
    </div>

    <!-- No layout configured: browse by group. -->
    <div
      v-else
      class="grid auto-rows-min content-start grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5"
    >
      <MenuTile
        v-for="group in groups"
        :key="group.name"
        class="min-h-[9.5rem]"
        :label="group.item_group_name"
        :image="group.image"
        placeholder="grid"
        @select="activeGroup = group.name"
      />
      <p
        v-if="!groups.length"
        class="col-span-full p-6 text-center text-muted"
      >
        {{ t("picker.empty") }}
      </p>
    </div>

    <!-- `D-378` — the price of a dish the shop prices at the counter, typed on
         the same pad as every other figure. Tapping outside sells nothing. -->
    <BaseDialog
      :open="Boolean(pricing)"
      :title="pricing ? itemName(pricing) : ''"
      pad
      @close="pricing = null"
    >
      <div class="flex flex-col gap-4">
        <AmountKeypad
          :value="typedPrice"
          :label="t('picker.typePrice')"
          @update="typedPrice = $event"
        />
        <button
          type="button"
          class="rpos-pad-done"
          :disabled="price <= 0"
          @click="priced"
        >
          {{ t("action.done") }}
        </button>
      </div>
    </BaseDialog>
  </div>
</template>
