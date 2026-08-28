<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { ModifierChoice, OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import LineDetailDialog from "@/components/order/LineDetailDialog.vue";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import OrderActionBar, { type OrderAction } from "@/components/order/OrderActionBar.vue";
import OrderPanel from "@/components/order/OrderPanel.vue";
import { pick, t } from "@/i18n";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";
import type { CatalogItem } from "@/types/session";

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

const title = computed(() => {
  const type = pick(orderType.value?.title_ar, orderType.value?.title);
  const table = orders.order?.table ? ` · ${orders.order.table}` : "";
  return `${type}${table}`;
});

const locked = computed(() => orders.busy || orders.isClosed);

/**
 * The order's own state, shown in the header where the cashier already looks.
 *
 * Colour follows the lifecycle and never carries the meaning alone: the pill
 * always spells the status out (06 §Accessibility).
 */
const STATUS_CLASS: Record<string, string> = {
  draft: "bg-order-draft/10 text-order-draft",
  active: "bg-order-active/10 text-order-active",
  in_kitchen: "bg-order-in_kitchen/10 text-order-in_kitchen",
  pending_payment: "bg-order-pending_payment/10 text-order-pending_payment",
  closed: "bg-order-closed/10 text-order-closed",
  cancelled: "bg-order-cancelled/10 text-order-cancelled",
};

const KNOWN_STATUSES = ["draft", "active", "in_kitchen", "pending_payment"] as const;

const statusLabel = computed(() => {
  const status = orders.order?.status;
  if (!status) return "";

  const known = KNOWN_STATUSES.find((candidate) => candidate === status);
  return known ? t(`status.${known}`) : status;
});

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
  else if (action.key === "cancel") cancelling.value = true;
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
    The same three rows as the till screen: identity, the work, the actions.
    `minmax(0, 1fr)` on the middle row is what lets both panels scroll inside it
    instead of growing the page (06 Screen 3).
  -->
  <main class="grid h-full grid-rows-[auto_minmax(0,1fr)_auto] bg-background">
    <header class="flex h-[90px] shrink-0 items-center gap-4 border-b border-line bg-surface px-6">
      <RouterLink
        :to="{ name: 'home' }"
        class="grid h-11 w-11 shrink-0 place-items-center rounded-full text-primary transition duration-200 ease-rpos hover:bg-background"
        :aria-label="t('action.back')"
      >
        <AppIcon
          name="back"
          class="rpos-flip"
          :size="24"
        />
      </RouterLink>

      <div class="min-w-0">
        <h1 class="truncate text-xl font-bold leading-tight">
          {{ title || t("order.title") }}
        </h1>
        <p
          v-if="orders.order"
          class="rpos-numeric truncate text-sm text-muted"
        >
          {{ orders.order.order_name }}
        </p>
      </div>

      <div class="ms-auto flex shrink-0 items-center gap-3">
        <span
          v-if="orders.busy"
          class="text-muted"
          :title="t('common.loading')"
        >
          <AppIcon
            name="refresh"
            class="animate-spin"
            :size="22"
          />
        </span>

        <span
          v-if="orders.order"
          class="rounded-full px-4 py-2 text-sm font-semibold"
          :class="STATUS_CLASS[orders.order.status] ?? 'bg-background text-muted'"
        >
          {{ statusLabel }}
        </span>
      </div>
    </header>

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
        <div class="grid min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-3">
          <!-- The order's actions sit over the menu, the way the reference
               system puts them: the bill stays a bill. -->
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

          <div class="grid min-h-0 grid-rows-[minmax(0,1fr)] rounded-rpos bg-surface p-4 shadow-card">
            <ItemPicker
              :order-type="orderType"
              :disabled="locked"
              @pick="onPick"
            />
          </div>
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

    <LineDetailDialog
      :line="inspecting"
      :busy="locked"
      @close="inspecting = null"
      @set-qty="changeQty"
      @void="voidFromDetail"
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
