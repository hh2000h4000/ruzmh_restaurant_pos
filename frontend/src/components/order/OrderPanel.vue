<script setup lang="ts">
import type { OrderDetail, OrderLine } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import { formatNumber, pick, t, timeOnly } from "@/i18n";

/**
 * The order side of Screen 3: the lines, then the totals.
 *
 * Three rows — heading, a list that scrolls, totals pinned at the foot — so the
 * total never leaves the screen no matter how long the order gets. That is the
 * figure the customer is being told.
 *
 * Every figure here came from the server. Nothing on this screen adds up a
 * column (`CLAUDE.md` §5.1); if it did, the customer could be told one number
 * and charged another.
 */
defineProps<{ order: OrderDetail; lines: OrderLine[]; busy?: boolean }>();

const emit = defineEmits<{
  void: [line: OrderLine];
  repeat: [line: OrderLine];
  inspect: [line: OrderLine];
}>();

/** A line already with the kitchen cannot be quietly re-tapped away (BR-013). */
function isSent(line: OrderLine): boolean {
  return line.status === "sent";
}

/** Bare figures: the currency is stated once, on the total. */
function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <section
    class="grid min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] rounded-rpos bg-surface shadow-card"
  >
    <header class="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
      <h2 class="flex items-center gap-2 text-lg font-bold">
        <AppIcon
          name="receipt"
          :size="22"
        />
        {{ t("panel.title") }}
      </h2>
      <div class="flex items-center gap-3">
        <p
          v-if="order.cover_count"
          class="text-sm text-muted"
        >
          <span class="rpos-numeric font-semibold text-content">{{
            formatNumber(order.cover_count)
          }}</span>
          {{ t("panel.covers") }}
        </p>
        <p
          v-if="order.opened_at"
          class="rpos-numeric text-sm text-muted"
        >
          {{ timeOnly(order.opened_at) }}
        </p>
        <span
          class="rpos-numeric grid h-9 min-w-[2.25rem] place-items-center rounded-full bg-primary/10 px-2 font-bold text-primary"
          :aria-label="t('panel.count')"
        >{{ formatNumber(lines.length) }}</span>
      </div>
    </header>

    <ul
      class="min-h-0 divide-y divide-line overflow-y-auto"
      :aria-label="t('panel.title')"
    >
      <li
        v-for="line in lines"
        :key="line.idx"
        class="relative p-4 transition duration-200 ease-rpos hover:bg-background/60"
      >
        <!-- The whole line opens its details; the two buttons below stay for
             the fast path a busy cashier already knows. -->
        <button
          type="button"
          class="absolute inset-0"
          :aria-label="line.item_name"
          @click="emit('inspect', line)"
        />

        <div class="pointer-events-none flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate font-semibold">
              {{ line.item_name }}
            </p>

            <p
              v-if="line.modifiers?.length"
              class="truncate text-sm text-muted"
            >
              {{
                line.modifiers
                  .map((modifier) => pick(modifier.option_ar, modifier.option))
                  .join(t("common.listSeparator"))
              }}
            </p>
            <p
              v-if="line.notes"
              class="flex items-center gap-1.5 truncate text-sm text-muted"
            >
              <AppIcon
                name="note"
                :size="14"
              />
              {{ line.notes }}
            </p>

            <!-- Status is never colour alone (06 §Accessibility). -->
            <p
              v-if="isSent(line)"
              class="mt-1.5 inline-block rounded-full bg-order-in_kitchen/10 px-2.5 py-0.5 text-xs font-medium text-order-in_kitchen"
            >
              {{ t("panel.inKitchen") }}
            </p>
          </div>

          <div class="shrink-0 text-end">
            <p class="rpos-numeric text-lg font-bold">
              {{ money(line.amount) }}
            </p>
            <p class="rpos-numeric text-sm text-muted">
              {{ formatNumber(line.qty) }} × {{ money(line.rate) }}
            </p>
          </div>
        </div>

        <div class="relative mt-3 flex items-center gap-2">
          <button
            type="button"
            class="ms-auto flex min-h-tap items-center gap-1.5 rounded-rpos px-3 text-sm font-medium text-primary transition duration-200 ease-rpos hover:bg-primary/10 disabled:opacity-40"
            :disabled="busy"
            @click="emit('repeat', line)"
          >
            <AppIcon
              name="plus"
              :size="18"
            />
            {{ t("panel.addSame") }}
          </button>

          <button
            type="button"
            class="flex min-h-tap items-center gap-1.5 rounded-rpos px-3 text-sm font-medium text-danger transition duration-200 ease-rpos hover:bg-danger/10 disabled:opacity-40"
            :disabled="busy"
            @click="emit('void', line)"
          >
            <AppIcon
              name="trash"
              :size="18"
            />
            {{ t("action.cancel") }}
          </button>
        </div>
      </li>

      <li
        v-if="!lines.length"
        class="grid place-items-center px-6 py-16 text-center"
      >
        <span class="mb-3 text-muted opacity-40">
          <AppIcon
            name="receipt"
            :size="44"
          />
        </span>
        <p class="text-muted">
          {{ t("panel.empty") }}
        </p>
      </li>
    </ul>

    <dl class="space-y-2 border-t border-line p-5">
      <div class="flex justify-between text-muted">
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
      <div class="flex justify-between text-muted">
        <dt>{{ t("totals.tax") }}</dt>
        <dd class="rpos-numeric">
          {{ money(order.tax_amount) }}
        </dd>
      </div>
      <div class="flex items-baseline justify-between border-t border-line pt-3">
        <dt class="text-lg font-bold">
          {{ t("totals.total") }}
        </dt>
        <dd class="rpos-numeric text-[26px] font-bold text-primary">
          {{ money(order.total_amount) }}
        </dd>
      </div>
    </dl>
  </section>
</template>
