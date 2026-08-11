<script setup lang="ts">
import type { OrderDetail, OrderLine } from "@/api/order";
import { formatNumber, pick, t } from "@/i18n";

/**
 * The order side of Screen 3: the lines, then the totals.
 *
 * Every figure shown here came from the server. Nothing on this screen adds up
 * a column (`CLAUDE.md` §5.1) — if it did, the customer could be told one
 * number and charged another.
 */
defineProps<{ order: OrderDetail; lines: OrderLine[]; busy?: boolean }>();

const emit = defineEmits<{
  void: [line: OrderLine];
  repeat: [line: OrderLine];
}>();

/** A line already with the kitchen cannot be quietly re-tapped away (BR-013). */
function isSent(line: OrderLine): boolean {
  return line.status === "sent";
}

/** Bare figures: the currency is stated once, in the payment screen's total. */
function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <div class="flex h-full flex-col rounded-rpos bg-surface">
    <ul
      class="flex-1 divide-y divide-line overflow-y-auto"
      :aria-label="t('panel.title')"
    >
      <li
        v-for="line in lines"
        :key="line.idx"
        class="p-3"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate font-medium">
              {{ line.item_name }}
            </p>

            <p
              v-if="line.modifiers?.length"
              class="truncate text-xs text-muted"
            >
              {{
                line.modifiers
                  .map((modifier) => pick(modifier.option_ar, modifier.option))
                  .join(t("common.listSeparator"))
              }}
            </p>
            <p
              v-if="line.notes"
              class="truncate text-xs text-muted"
            >
              ✎ {{ line.notes }}
            </p>

            <!-- Status is never colour alone (06 §Accessibility). -->
            <p
              v-if="isSent(line)"
              class="mt-1 inline-block rounded bg-order-in_kitchen/10 px-1.5 text-xs text-order-in_kitchen"
            >
              {{ t("panel.inKitchen") }}
            </p>
          </div>

          <p class="rpos-numeric shrink-0 font-medium">
            {{ money(line.amount) }}
          </p>
        </div>

        <div class="mt-2 flex items-center gap-2">
          <span class="rpos-numeric text-sm text-muted">×{{ line.qty }}</span>

          <button
            type="button"
            class="min-h-tap rounded-rpos border border-line px-3 text-sm disabled:opacity-50"
            :disabled="busy"
            @click="emit('repeat', line)"
          >
            + {{ t("panel.addSame") }}
          </button>

          <button
            type="button"
            class="min-h-tap rounded-rpos px-3 text-sm text-danger disabled:opacity-50"
            :disabled="busy"
            @click="emit('void', line)"
          >
            🗑 {{ t("action.cancel") }}
          </button>
        </div>
      </li>

      <li
        v-if="!lines.length"
        class="p-8 text-center text-muted"
      >
        {{ t("panel.empty") }}
      </li>
    </ul>

    <dl class="space-y-1 border-t border-line p-4 text-sm">
      <div class="flex justify-between">
        <dt>{{ t("totals.subtotal") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.subtotal) }}
        </dd>
      </div>
      <div
        v-if="order.discount_amount"
        class="flex justify-between text-status-available"
      >
        <dt>{{ t("totals.discount") }}</dt>
        <dd class="rpos-numeric">
          −{{ money(order.discount_amount) }}
        </dd>
      </div>
      <div class="flex justify-between">
        <dt>{{ t("totals.tax") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.tax_amount) }}
        </dd>
      </div>
      <div class="flex justify-between border-t border-line pt-2 text-base font-semibold">
        <dt>{{ t("totals.total") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.total_amount) }}
        </dd>
      </div>
    </dl>
  </div>
</template>
