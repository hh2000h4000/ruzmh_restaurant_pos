<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { ModifierChoice, OrderLine } from "@/api/order";
import BaseDialog from "@/components/BaseDialog.vue";
import ItemPicker from "@/components/order/ItemPicker.vue";
import ModifierDialog from "@/components/order/ModifierDialog.vue";
import OrderPanel from "@/components/order/OrderPanel.vue";
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
const voidTarget = ref<OrderLine | null>(null);
const voidReason = ref("");
const cancelling = ref(false);
const cancelReason = ref("");

const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orders.order?.order_type) ?? null,
);

const title = computed(() => {
  const type = orderType.value?.title_ar ?? "";
  const table = orders.order?.table ? ` · ${orders.order.table}` : "";
  return `${type}${table}`;
});

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
    startupError.value = "نوع الطلب غير متاح على هذا الجهاز.";
    return;
  }

  // A table-service order arrives here already created by the table picker, so
  // reaching this branch means the cashier deep-linked past it.
  if (type.requires_table) {
    startupError.value = "اختر طاولة أولاً.";
    return;
  }

  // The customer picker is its own flow (FR-2.1 step 4) and does not exist yet.
  if (type.customer_mode === "required") {
    startupError.value = "هذا النوع يتطلب اختيار عميل — شاشة العملاء قيد التنفيذ.";
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
function onPick(item: CatalogItem): void {
  if (item.modifier_groups.length) {
    pendingItem.value = item;
    return;
  }
  void orders.addItem(item.item_code);
}

function onModifiersConfirmed(payload: { modifiers: ModifierChoice[]; notes: string }): void {
  const item = pendingItem.value;
  pendingItem.value = null;
  if (!item) return;

  void orders.addItem(item.item_code, {
    modifiers: payload.modifiers,
    notes: payload.notes || null,
  });
}

function repeat(line: OrderLine): void {
  void orders.addItem(line.item, { qty: 1 });
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

async function send(): Promise<void> {
  await orders.sendToKitchen();
}
</script>

<template>
  <main class="flex h-screen flex-col">
    <header class="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
      <div class="flex items-center gap-3">
        <RouterLink
          :to="{ name: 'home' }"
          class="rpos-tap inline-flex items-center px-2 text-primary"
        >
          ←
        </RouterLink>
        <div>
          <h1 class="font-semibold">
            {{ title }}
          </h1>
          <p
            v-if="orders.order"
            class="rpos-numeric text-xs text-muted"
          >
            {{ orders.order.order_name }}
          </p>
        </div>
      </div>
      <span
        v-if="orders.busy"
        class="text-sm text-muted"
      >…</span>
    </header>

    <p
      v-if="startupError"
      role="alert"
      class="m-4 rounded-rpos bg-danger/10 p-4 text-danger"
    >
      {{ startupError }}
    </p>

    <p
      v-else-if="orders.error"
      role="alert"
      class="m-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ orders.error }}
    </p>

    <p
      v-if="orders.unrouted.length"
      role="status"
      class="mx-4 mt-2 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
    >
      لم يُوجَّه للمطبخ: {{ orders.unrouted.join("، ") }} — ستُطبع على طابعة الكاشير.
    </p>

    <div
      v-if="orders.order"
      class="grid flex-1 gap-3 overflow-hidden p-3 lg:grid-cols-[3fr_2fr]"
    >
      <ItemPicker
        :order-type="orderType"
        :disabled="locked"
        @pick="onPick"
      />
      <OrderPanel
        :order="orders.order"
        :lines="orders.lines"
        :busy="locked"
        @void="askVoid"
        @repeat="repeat"
      />
    </div>

    <footer
      v-if="orders.order && !orders.isClosed"
      class="flex flex-wrap gap-2 border-t border-line bg-surface p-3"
    >
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-secondary px-4 font-medium text-secondary-contrast disabled:opacity-50"
        :disabled="locked || !orders.hasUnsent"
        @click="send"
      >
        🍳 إرسال للمطبخ
      </button>

      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary px-4 font-medium text-primary-contrast disabled:opacity-50"
        :disabled="locked || orders.isEmpty"
        @click="router.push({ name: 'payment', params: { orderName: orders.order.order_name } })"
      >
        💳 دفع
      </button>

      <button
        v-if="session.can('can_cancel_order')"
        type="button"
        class="min-h-tap rounded-rpos border border-danger px-4 text-danger disabled:opacity-50"
        :disabled="locked"
        @click="cancelling = true"
      >
        🚫 إلغاء الطلب
      </button>
    </footer>

    <ModifierDialog
      :item="pendingItem"
      @confirm="onModifiersConfirmed"
      @cancel="pendingItem = null"
    />

    <!-- BR-013: a reason is mandatory, so this dialog cannot be dismissed away. -->
    <BaseDialog
      :open="Boolean(voidTarget)"
      title="سبب الإلغاء"
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
        placeholder="مثال: طلب الزبون التغيير"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="voidTarget = null"
        >
          تراجع
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!voidReason.trim()"
          @click="confirmVoid"
        >
          إلغاء الصنف
        </button>
      </div>
    </BaseDialog>

    <BaseDialog
      :open="cancelling"
      title="إلغاء الطلب"
      @close="cancelling = false"
    >
      <p class="mb-3 text-sm text-muted">
        سيُلغى الطلب بالكامل، وسيُبلَّغ المطبخ بما أُرسل إليه.
      </p>
      <input
        v-model="cancelReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
        placeholder="سبب الإلغاء"
      >
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="cancelling = false"
        >
          تراجع
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
          :disabled="!cancelReason.trim()"
          @click="confirmCancel"
        >
          تأكيد الإلغاء
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
