<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { ModifierChoice, OpenOrder, OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import LineDetailDialog from "@/components/order/LineDetailDialog.vue";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import OrderActionBar, { type OrderAction } from "@/components/order/OrderActionBar.vue";
import OrderPanel from "@/components/order/OrderPanel.vue";
import OrderTypeChangeDialog from "@/components/order/OrderTypeChangeDialog.vue";
import FloorPane from "@/components/order/FloorPane.vue";
import NewOrderPane from "@/components/order/NewOrderPane.vue";
import OrderBottomNav, { type NavEntry } from "@/components/order/OrderBottomNav.vue";
import OpenOrdersPanel from "@/components/pos/OpenOrdersPanel.vue";
import { useOpenOrders } from "@/composables/useOpenOrders";
import { formatNumber, t } from "@/i18n";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import type { FloorTable } from "@/api/table";
import type { CatalogItem, OrderType } from "@/types/session";

/**
 * Screen 3 — the screen a cashier spends the whole shift on.
 *
 * Opens an existing order by name, or creates one for the order type the home
 * screen chose. Every action is a server call; nothing about the order is
 * decided here (`02_backend_rules.md`).
 */
const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const orders = useOrderStore();

const startupError = ref<string | null>(null);
const pendingItem = ref<CatalogItem | null>(null);
const pendingQty = ref(1);
const voidTarget = ref<OrderLine | null>(null);
const voidReason = ref("");
const cancelling = ref(false);
const cancelReason = ref("");

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orders.order?.order_type) ?? null,
);

const locked = computed(() => orders.busy || orders.isClosed);

onMounted(async () => {
  const existing = route.params.orderName as string | undefined;
  if (existing) {
    await orders.open(existing);
    return;
  }

  const typeName = route.params.orderType as string;
  const type = session.orderTypes.find((candidate) => candidate.name === typeName);
  if (!type) {
    startupError.value = t("order.typeUnavailable");
    return;
  }

  // A table-service order arrives here already created by the table picker, so
  // reaching this branch means the cashier deep-linked past it.
  if (type.requires_table) {
    startupError.value = t("order.pickTableFirst");
    return;
  }

  // The customer picker is its own flow (FR-2.1 step 4) and does not exist yet.
  if (type.customer_mode === "required") {
    startupError.value = t("order.customerPending");
    return;
  }

  const created = await orders.create({
    order_type: type.name,
    pos_profile: session.profile!.name,
  });

  if (created) {
    await router.replace({ name: "order", params: { orderName: created } });
  }
});

// --------------------------------------------------------------------------
// The working column (D-039)
// --------------------------------------------------------------------------

/**
 * The bill stays; only this column changes.
 *
 * Leaving the screen to look at the floor is what made the old flow feel like
 * two applications. Here the order in hand is never put down.
 */
const pane = ref("items");
const floorLayout = ref<"list" | "grid">("list");
const {
  error: floorError,
  loading: floorLoading,
  maySeeEveryone: floorMaySeeEveryone,
  scope: floorScope,
  searching: floorSearching,
  view: floorView,
  visible: floorOrders,
} = useOpenOrders();

/**
 * The four places, along the bottom (D-042).
 *
 * "New" sits among them rather than above them. It is the one entry that
 * changes something — it leaves the order in hand open and starts another — but
 * a filled block among four signposts turns a bar into an advertisement.
 */
const navEntries = computed<NavEntry[]>(() => [
  { key: "items", label: "order.paneItems", icon: "grid" },
  {
    key: "orders",
    label: "nav.orders",
    icon: "document",
    count: floorView.value === "open" ? floorOrders.value.length : 0,
  },
  { key: "tables", label: "nav.tables", icon: "floorPlan" },
  { key: "new", label: "nav.new", icon: "plus" },
]);

function onNavigate(key: string): void {
  // Walking away from the question cancels it; a table still marked "waiting"
  // would seat the next type the cashier taps for an unrelated reason.
  if (key !== "new") pendingTable.value = null;

  if (key === "home") void router.push({ name: "home" });
  else pane.value = key;
}

/**
 * Start another order and leave this one open (D-042).
 *
 * Nothing is "held": the order in hand is already a `Restaurant Order` on the
 * server, and the cashier finds it again under **الطلبات**. A customer who
 * takes their time paying stops blocking the queue, and no new concept was
 * needed to allow it.
 */
async function startAnother(orderType: OrderType): Promise<void> {
  // FR-2.1 step 4 — its own flow, and it does not exist yet. The pane already
  // greys these out; this is the guard behind the guard.
  if (orderType.customer_mode === "required") return;

  // The cashier came here from a table they had already tapped: this answers
  // the question the floor could not.
  const waiting = pendingTable.value;
  if (waiting) {
    await openAt(waiting, orderType);
    return;
  }

  // **Only** when the type says so. A restaurant with no table plan opens
  // dine-in and the customer takes a seat; `requires_table` is what decides,
  // per type, and it always has been (05 §Restaurant Order Type).
  if (orderType.requires_table) {
    // A type that seats people picks the table first, so the order is never
    // created and then refused (FR-2.1 step 3).
    pane.value = "tables";
    seatingType.value = orderType;
    return;
  }

  // BR-064 — the guest count is its own setting, and a type can want one
  // without seating anybody. Ask, rather than send an order the server will
  // refuse for a number nobody was offered the chance to give.
  if (orderType.requires_cover_count) {
    countingType.value = orderType;
    covers.value = 2;
    return;
  }

  const created = await orders.create({
    order_type: orderType.name,
    pos_profile: session.profile!.name,
  });

  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

/**
 * The type waiting for a guest count, when it wants one and seats nobody.
 *
 * `null` closes the prompt. Two is the opening guess: two is the commonest
 * party in any restaurant that counts covers at all.
 */
const countingType = ref<OrderType | null>(null);
const covers = ref(2);

async function confirmCovers(): Promise<void> {
  const orderType = countingType.value;
  if (!orderType || covers.value < 1) return;

  countingType.value = null;
  const created = await orders.create({
    order_type: orderType.name,
    pos_profile: session.profile!.name,
    cover_count: covers.value,
  });

  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

/**
 * The type waiting for a table, when the cashier came here from **New**.
 *
 * `null` means the floor is just being looked at, and tapping a free table
 * seats whichever type this terminal uses for table service.
 */
const seatingType = ref<OrderType | null>(null);

/**
 * A table waiting for the cashier to say what kind of order to open on it.
 *
 * `null` means nothing is waiting. Set when tapping a free table could not
 * settle the type on its own — see `seat`.
 */
const pendingTable = ref<FloorTable | null>(null);

/**
 * Types this terminal would open *by* picking a table first.
 *
 * A hint, not the rule. `requires_table` answers "must a table be chosen
 * before the order opens" — a workflow question — and a restaurant that turns
 * it off still has tables and still seats people at them (FR-2.1a). So when it
 * settles the question it is used, and when it does not the cashier is asked.
 */
const tableTypes = computed(() => session.orderTypes.filter((type) => type.requires_table));

async function seat(table: FloorTable): Promise<void> {
  // One candidate is an answer. None — because no type demands a table — and
  // several are both guesses, and guessing here opens the wrong kind of order
  // on a real table.
  const type = seatingType.value ?? (tableTypes.value.length === 1 ? tableTypes.value[0] : null);

  if (!type) {
    pendingTable.value = table;
    pane.value = "new";
    return;
  }

  await openAt(table, type);
}

/** Open an order of this type, seated at this table. */
async function openAt(table: FloorTable, type: OrderType): Promise<void> {
  const created = await orders.create({
    order_type: type.name,
    pos_profile: session.profile!.name,
    table: table.name,
    cover_count: type.requires_cover_count ? table.capacity || 2 : null,
  });

  seatingType.value = null;
  pendingTable.value = null;
  if (created) {
    pane.value = "items";
    await router.replace({ name: "order", params: { orderName: created } });
  }
}

/**
 * Switch the screen to another open order without unmounting it.
 *
 * `router.replace` keeps the address honest — a reload lands on the order the
 * cashier is actually looking at — and the watch below does the reading.
 */
function switchTo(order: OpenOrder): void {
  openOrder(order.name);
}

function openOrder(orderName: string): void {
  pane.value = "items";
  if (orderName === orders.order?.order_name) return;
  void router.replace({ name: "order", params: { orderName } });
}

watch(
  () => route.params.orderName,
  (name) => {
    if (typeof name === "string" && name && name !== orders.order?.order_name) {
      void orders.open(name);
    }
  },
);


/** FR-2.2 — an item with modifier groups opens the popup first. */
function onPick(item: CatalogItem, qty: number): void {
  if (item.modifier_groups.length) {
    // The quantity has to survive the detour, or six coffees with extra milk
    // arrive as one.
    pendingItem.value = item;
    pendingQty.value = qty;
    return;
  }
  void orders.addItem(item.item_code, { qty });
}

function onModifiersConfirmed(payload: { modifiers: ModifierChoice[]; notes: string }): void {
  const item = pendingItem.value;
  const qty = pendingQty.value;
  clearPending();
  if (!item) return;

  void orders.addItem(item.item_code, {
    qty,
    modifiers: payload.modifiers,
    notes: payload.notes || null,
  });
}

function clearPending(): void {
  pendingItem.value = null;
  pendingQty.value = 1;
}

function repeat(line: OrderLine): void {
  void orders.addItem(line.item, { qty: 1 });
}

/** Tapping a line opens everything known about it (06 Screen 3). */
const inspecting = ref<OrderLine | null>(null);

function inspect(line: OrderLine): void {
  inspecting.value = line;
}

/** Keep the open dialog pointing at the line as the order is re-read. */
watch(
  () => orders.lines,
  (lines) => {
    if (!inspecting.value) return;
    inspecting.value = lines.find((line) => line.idx === inspecting.value?.idx) ?? null;
  },
);

async function changeQty(idx: number, qty: number): Promise<void> {
  await orders.setQty(idx, qty);
}

function voidFromDetail(line: OrderLine): void {
  inspecting.value = null;
  askVoid(line);
}

function askVoid(line: OrderLine): void {
  voidTarget.value = line;
  voidReason.value = "";
}

async function confirmVoid(): Promise<void> {
  const line = voidTarget.value;
  if (!line || !voidReason.value.trim()) return;

  voidTarget.value = null;
  await orders.voidLine(line.idx, voidReason.value.trim());
}

async function confirmCancel(): Promise<void> {
  if (!cancelReason.value.trim()) return;

  const done = await orders.cancel(cancelReason.value.trim());
  cancelling.value = false;
  if (done) await router.push({ name: "home" });
}

// --------------------------------------------------------------------------
// The action row (06 Screen 3, D-037)
// --------------------------------------------------------------------------

/**
 * What a cashier reaches for without looking. Kept short on purpose: the row
 * has to stay one line at 1280px and shrink cleanly when a permission removes
 * an entry.
 */
const rowActions = computed<OrderAction[]>(() => [
  {
    key: "kitchen",
    label: "order.sendToKitchen",
    icon: "kitchen",
    disabled: locked.value || !orders.hasUnsent,
  },
  {
    key: "refresh",
    label: "action.refresh",
    icon: "refresh",
    disabled: orders.busy,
  },
]);

/**
 * Everything else, one deliberate tap further away.
 *
 * Cancelling is here rather than in the row because the row is where a busy
 * hand lands without looking, and this one cannot be taken back.
 */
const moreActions = computed<OrderAction[]>(() => {
  const entries: OrderAction[] = [];

  // D-038 — offered only where a conversion is possible at all: an app order
  // is billed to the platform and can never become a walk-in sale.
  if (session.can("can_change_order_type") && orderType.value?.counterparty === "walk_in") {
    entries.push({
      key: "convert",
      label: "convert.action",
      icon: "swap",
      disabled: locked.value,
    });
  }

  if (session.can("can_cancel_order")) {
    entries.push({
      key: "cancel",
      label: "order.cancelOrder",
      icon: "ban",
      disabled: locked.value,
      destructive: true,
    });
  }

  return entries;
});

function onAction(action: OrderAction): void {
  if (action.key === "kitchen") void send();
  else if (action.key === "refresh") void reload();
  else if (action.key === "convert") converting.value = true;
  else if (action.key === "cancel") cancelling.value = true;
}

// --------------------------------------------------------------------------
// Changing the type (D-038)
// --------------------------------------------------------------------------

const converting = ref(false);

async function convert(orderType: string, coverCount: number | null): Promise<void> {
  converting.value = false;
  await orders.changeType(orderType, { coverCount });
}

/**
 * A type that seats people needs a table, and the dialog is not a floor plan.
 *
 * The floor plan is told which order is being converted, so it seats this one
 * instead of opening a second.
 */
function convertWithTable(orderType: string): void {
  converting.value = false;
  if (!orders.order) return;

  void router.push({
    name: "tables",
    params: { orderType },
    query: { convert: orders.order.order_name },
  });
}

/** Another till may have added to this order; re-read rather than guess. */
async function reload(): Promise<void> {
  if (orders.order) await orders.open(orders.order.order_name);
}

function goToPayment(): void {
  if (!orders.order) return;
  void router.push({ name: "payment", params: { orderName: orders.order.order_name } });
}

async function send(): Promise<void> {
  await orders.sendToKitchen();
}
</script>

<template>
  <!--
    No title bar. A till screen is read from across a counter, and ninety pixels
    of chrome repeating what the bill already says is ninety pixels of menu the
    cashier does not get. Everything that lived up there has a better home: the
    order's number, state, type and customer are on the bill; the way back is
    the button beside the tabs.
  -->
  <main class="grid h-full grid-rows-[minmax(0,1fr)] bg-background">
    <div class="grid min-h-0 grid-rows-[minmax(0,1fr)] p-5">
      <p
        v-if="startupError"
        role="alert"
        class="self-start rounded-rpos bg-danger/10 p-4 text-danger"
      >
        {{ startupError }}
      </p>

      <div
        v-else-if="orders.order"
        class="grid min-h-0 gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"
      >
        <!--
          A column, not a row template. The notices below are `empty:hidden`, so
          on a quiet screen they are not a grid item at all — and every child
          after them slid up a row: the menu took the `auto` track and the nav
          took `minmax(0, 1fr)`, which stretched it to 374px. It came right
          again the moment an error appeared, which is why it looked like the
          bar changed size on its own.

          Flex asks each child what it wants instead of counting them, so the
          pane grows and the two bars keep their own height whatever is on
          screen.
        -->
        <div class="flex min-h-0 flex-col gap-3">
          <!-- What the order can do. Where the cashier goes is the bar along
               the bottom; the two never mix (D-042). -->
          <OrderActionBar
            :actions="rowActions"
            :more="moreActions"
            @select="onAction"
          />

          <div class="flex flex-col gap-2 empty:hidden">
            <p
              v-if="orders.error"
              role="alert"
              class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
            >
              {{ orders.error }}
            </p>

            <!-- 09 §10 — an order carrying queued work must say so, or the
                 cashier reads a confirmation the server never got. -->
            <p
              v-if="orders.pendingSync"
              role="status"
              class="flex items-center gap-2 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
            >
              <AppIcon
                name="hourglass"
                :size="18"
              />
              {{ t("order.pendingSync") }}
            </p>

            <p
              v-if="orders.unrouted.length"
              role="status"
              class="rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
            >
              {{ t("order.notRouted", { items: orders.unrouted.join(t("common.listSeparator")) }) }}
            </p>
          </div>

          <div
            v-if="pane === 'items'"
            class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] rounded-rpos bg-surface p-4 shadow-card"
          >
            <ItemPicker
              :order-type="orderType"
              :disabled="locked"
              @pick="onPick"
            />
          </div>

          <!-- The same list as the till screen, in the same component: one
               place decides what an order looks like. Here it can also be asked
               for drafts and for today's history (D-042). -->
          <OpenOrdersPanel
            v-else-if="pane === 'orders'"
            v-model:layout="floorLayout"
            class="min-h-0 flex-1"
            :orders="floorOrders"
            :loading="floorLoading"
            :error="floorError"
            :searching="floorSearching"
            :scope="floorMaySeeEveryone ? floorScope : null"
            :view="floorView"
            @open="switchTo"
            @floor-plan="pane = 'tables'"
            @update:scope="floorScope = $event"
            @update:view="floorView = $event"
          />

          <FloorPane
            v-else-if="pane === 'tables'"
            class="min-h-0 flex-1"
            @seat="seat"
            @open="openOrder"
          />

          <NewOrderPane
            v-else
            class="min-h-0 flex-1"
            :seating="pendingTable?.table_number ?? null"
            @open="startAnother"
          />

          <!-- Under the working column, so the bill beside it keeps the full
               height of the screen (06 Screen 3). -->
          <OrderBottomNav
            :entries="navEntries"
            :active="pane"
            @select="onNavigate"
          />
        </div>

        <OrderPanel
          :order="orders.order"
          :lines="orders.lines"
          :busy="locked"
          :can-pay="!locked && !orders.isEmpty"
          @void="askVoid"
          @repeat="repeat"
          @inspect="inspect"
          @pay="goToPayment"
        />
      </div>
    </div>

    <!-- BR-064 — only where the order type asks for it (FR-2.1a). -->
    <BaseDialog
      :open="Boolean(countingType)"
      :title="t('covers.title')"
      :dismissible="true"
      @close="countingType = null"
    >
      <p class="mb-4 text-sm text-muted">
        {{ t("covers.body") }}
      </p>

      <div class="mb-5 flex items-center justify-center gap-4">
        <button
          type="button"
          class="grid h-14 w-14 place-items-center rounded-full bg-background text-muted transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary disabled:opacity-40"
          :disabled="covers <= 1"
          :aria-label="t('picker.qtyLess')"
          @click="covers = Math.max(1, covers - 1)"
        >
          <AppIcon
            name="minus"
            :size="24"
          />
        </button>

        <span class="rpos-numeric w-16 text-center text-3xl font-bold">{{
          formatNumber(covers)
        }}</span>

        <button
          type="button"
          class="grid h-14 w-14 place-items-center rounded-full bg-background text-muted transition duration-200 ease-rpos hover:bg-primary/10 hover:text-primary"
          :aria-label="t('picker.qtyMore')"
          @click="covers = covers + 1"
        >
          <AppIcon
            name="plus"
            :size="24"
          />
        </button>
      </div>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="countingType = null"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
          :disabled="orders.busy"
          @click="confirmCovers"
        >
          {{ t("home.newOrder") }}
        </button>
      </div>
    </BaseDialog>

    <LineDetailDialog
      :line="inspecting"
      :busy="locked"
      @close="inspecting = null"
      @set-qty="changeQty"
      @void="voidFromDetail"
    />

    <OrderTypeChangeDialog
      v-if="orders.order"
      :open="converting"
      :order-name="orders.order.order_name"
      :current-type="orders.order.order_type"
      :cover-count="orders.order.cover_count"
      :busy="orders.busy"
      @close="converting = false"
      @confirm="convert"
      @pick-table="convertWithTable"
    />

    <ModifierDialog
      :item="pendingItem"
      @confirm="onModifiersConfirmed"
      @cancel="clearPending"
    />

    <!-- BR-013: a reason is mandatory, so this cannot be dismissed away. -->
    <BaseDialog
      :open="Boolean(voidTarget)"
      :title="t('order.voidReason')"
      :dismissible="true"
      @close="voidTarget = null"
    >
      <p class="mb-3 text-sm text-muted">
        {{ voidTarget?.item_name }}
      </p>
      <input
        v-model="voidReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
        :placeholder="t('order.voidPlaceholder')"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="voidTarget = null"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!voidReason.trim()"
          @click="confirmVoid"
        >
          {{ t("order.voidItem") }}
        </button>
      </div>
    </BaseDialog>

    <BaseDialog
      :open="cancelling"
      :title="t('order.cancelOrder')"
      @close="cancelling = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("order.cancelBody") }}
      </p>
      <input
        v-model="cancelReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
        :placeholder="t('order.voidReason')"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="cancelling = false"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!cancelReason.trim()"
          @click="confirmCancel"
        >
          {{ t("order.confirmCancel") }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
