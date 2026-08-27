<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Everything known about one line, and the things that can still be done to it.
 *
 * Tapping a line on the bill opens this instead of hunting for small buttons on
 * a crowded row — the reference system does the same, and on a touch screen it
 * is the difference between hitting the line you meant and the one below it.
 *
 * What is *not* here is as deliberate as what is. Per-item discounts, recipes,
 * stock and a scale reading all appear on the reference screen; each needs a
 * backend that does not exist yet, and a button that does nothing is worse than
 * no button.
 */
const props = defineProps<{ line: OrderLine | null; busy?: boolean }>();

const emit = defineEmits<{
  close: [];
  setQty: [idx: number, qty: number];
  void: [line: OrderLine];
}>();

const session = useSessionStore();

const qty = ref(1);

watch(
  () => props.line,
  (line) => {
    qty.value = line ? line.qty : 1;
  },
  { immediate: true },
);

/** BR-013 — a line the kitchen already has is withdrawn, not edited. */
const editable = computed(() => props.line?.status === "pending");

const item = computed(() =>
  props.line ? (session.itemsByCode.get(props.line.item) ?? null) : null,
);

const modifiers = computed(() =>
  (props.line?.modifiers ?? [])
    .map((modifier) => pick(modifier.option_ar, modifier.option))
    .join(t("common.listSeparator")),
);

function money(value: number): string {
  return formatNumber(value, 2);
}

function bump(by: number): void {
  qty.value = Math.min(99, Math.max(1, qty.value + by));
}

function apply(): void {
  if (!props.line || !editable.value || qty.value === props.line.qty) return;
  emit("setQty", props.line.idx, qty.value);
}
</script>

<template>
  <BaseDialog
    :open="Boolean(line)"
    :title="line?.item_name ?? ''"
    :dismissible="true"
    @close="emit('close')"
  >
    <template v-if="line">
      <!-- The dish, when the menu carries a picture of it. -->
      <img
        v-if="item?.image"
        :src="item.image"
        :alt="line.item_name"
        class="mb-4 h-40 w-full rounded-rpos object-cover"
      >

      <dl class="mb-4 grid grid-cols-2 gap-4">
        <div>
          <dt class="text-sm text-muted">
            {{ t("line.number") }}
          </dt>
          <dd class="rpos-numeric font-bold">
            {{ formatNumber(line.idx) }}
          </dd>
        </div>
        <div class="min-w-0">
          <dt class="text-sm text-muted">
            {{ t("line.item") }}
          </dt>
          <dd class="rpos-numeric truncate font-bold">
            {{ line.item }}
          </dd>
        </div>
        <div>
          <dt class="text-sm text-muted">
            {{ t("line.unitPrice") }}
          </dt>
          <dd class="rpos-numeric font-bold">
            {{ money(line.rate) }}
          </dd>
        </div>
        <div>
          <dt class="text-sm text-muted">
            {{ t("card.amount") }}
          </dt>
          <dd class="rpos-numeric text-lg font-bold text-primary">
            {{ money(line.amount) }}
          </dd>
        </div>
        <div
          v-if="line.production_center"
          class="col-span-2 min-w-0"
        >
          <dt class="text-sm text-muted">
            {{ t("line.station") }}
          </dt>
          <dd class="truncate font-medium">
            {{ line.production_center }}
          </dd>
        </div>
        <div
          v-if="modifiers"
          class="col-span-2 min-w-0"
        >
          <dt class="text-sm text-muted">
            {{ t("line.modifiers") }}
          </dt>
          <dd class="font-medium">
            {{ modifiers }}
          </dd>
        </div>
        <div
          v-if="line.notes"
          class="col-span-2 min-w-0"
        >
          <dt class="text-sm text-muted">
            {{ t("mod.note") }}
          </dt>
          <dd class="font-medium">
            {{ line.notes }}
          </dd>
        </div>
      </dl>

      <p
        v-if="!editable"
        class="mb-4 rounded-rpos bg-order-in_kitchen/10 p-3 text-sm text-order-in_kitchen"
      >
        {{ t("line.sentLocked") }}
      </p>

      <!-- Quantity, while the kitchen has not seen the line. -->
      <div
        v-else
        class="mb-4"
      >
        <p class="mb-2 text-sm font-medium">
          {{ t("picker.qty") }}
        </p>
        <div class="flex items-center gap-2">
          <button
            type="button"
            class="grid h-12 w-12 place-items-center rounded-full bg-background text-muted disabled:opacity-40"
            :disabled="qty <= 1 || busy"
            :aria-label="t('picker.qtyLess')"
            @click="bump(-1)"
          >
            <AppIcon name="minus" />
          </button>
          <span
            class="rpos-numeric w-14 text-center text-2xl font-bold"
            aria-live="polite"
          >{{ formatNumber(qty) }}</span>
          <button
            type="button"
            class="grid h-12 w-12 place-items-center rounded-full bg-background text-muted disabled:opacity-40"
            :disabled="qty >= 99 || busy"
            :aria-label="t('picker.qtyMore')"
            @click="bump(1)"
          >
            <AppIcon name="plus" />
          </button>

          <button
            type="button"
            class="ms-auto min-h-tap rounded-rpos bg-primary px-5 font-semibold text-primary-contrast disabled:opacity-40"
            :disabled="busy || qty === line.qty"
            @click="apply"
          >
            {{ t("line.applyQty") }}
          </button>
        </div>
      </div>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="emit('close')"
        >
          {{ t("action.back") }}
        </button>
        <button
          type="button"
          class="flex min-h-tap flex-1 items-center justify-center gap-2 rounded-rpos bg-danger/10 font-semibold text-danger disabled:opacity-40"
          :disabled="busy"
          @click="emit('void', line)"
        >
          <AppIcon
            name="trash"
            :size="18"
          />
          {{ t("order.voidItem") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
