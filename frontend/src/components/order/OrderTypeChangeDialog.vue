<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { previewOrderTypeChange, type OrderTypeChangePreview } from "@/api/order";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

/**
 * Turning an open order into another type (D-038).
 *
 * **Why the app types are still listed.** An order billed to a platform or a
 * company cannot be converted — the debt would move to somebody who ordered
 * nothing — so they appear greyed with the reason written out. Hiding them
 * would leave the cashier asking where HungerStation went; one disabled row
 * teaches the rule once and is never asked about again.
 *
 * **Why a preview.** The new type may sell from another price list, and a total
 * already read out to a customer does not change without them hearing it first.
 * The server computes both figures; nothing here adds anything up.
 */
const props = defineProps<{
  open: boolean;
  orderName: string;
  currentType: string;
  /** What the order already records, so a type that wants a count may not ask. */
  coverCount: number;
  busy?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  /** The cashier confirmed a type this order can take as it stands. */
  confirm: [orderType: string, coverCount: number | null];
  /** The target seats people; the order has to pick a table first. */
  pickTable: [orderType: string];
}>();

const session = useSessionStore();

const current = computed(
  () => session.orderTypes.find((type) => type.name === props.currentType) ?? null,
);

/**
 * Every type the terminal offers, convertible ones first.
 *
 * The order is stable — permissions may remove an entry, but the survivors keep
 * their positions, because a cashier learns them by hand (D-037).
 */
const options = computed(() => {
  const rows = session.orderTypes.filter((type) => type.name !== props.currentType);
  return [...rows].sort((a, b) => Number(!convertible(a)) - Number(!convertible(b)));
});

/** D-038 — both sides must bill the customer standing there. */
function convertible(type: OrderType): boolean {
  return type.counterparty === "walk_in" && current.value?.counterparty === "walk_in";
}

function reasonFor(type: OrderType): string {
  if (type.counterparty !== "walk_in") return t("convert.targetIsAccount");
  return t("convert.sourceIsAccount");
}

// --------------------------------------------------------------------------
// The preview
// --------------------------------------------------------------------------

const chosen = ref<OrderType | null>(null);
const preview = ref<OrderTypeChangePreview | null>(null);
const loading = ref(false);
const failure = ref<string | null>(null);

async function choose(type: OrderType): Promise<void> {
  if (!convertible(type)) return;

  chosen.value = type;
  preview.value = null;
  failure.value = null;
  loading.value = true;

  try {
    preview.value = await previewOrderTypeChange({
      order_name: props.orderName,
      order_type: type.name,
    });
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

const priceChanged = computed(
  () => Boolean(preview.value) && preview.value!.total_after !== preview.value!.total_before,
);

/** A type that seats people needs a table, and this dialog is not a floor plan. */
const needsTable = computed(() => Boolean(preview.value?.requires_table));

/**
 * BR-064 — the new type counts guests and this order has never been asked.
 *
 * Only where no table is involved: seating the order supplies the number from
 * the table's capacity. Without this the conversion was refused in red for a
 * figure the dialog knew it needed and never offered a way to give.
 */
const needsCovers = computed(
  () =>
    Boolean(preview.value?.requires_cover_count) && !needsTable.value && props.coverCount < 1,
);

const covers = ref(2);

function confirm(): void {
  const type = chosen.value;
  if (!type || loading.value) return;

  if (needsTable.value) emit("pickTable", type.name);
  else emit("confirm", type.name, needsCovers.value ? covers.value : null);
}

/** Reopening must not show the answer to the last question. */
watch(
  () => props.open,
  (open) => {
    if (open) return;
    chosen.value = null;
    preview.value = null;
    failure.value = null;
    covers.value = 2;
  },
);

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('convert.title')"
    @close="emit('close')"
  >
    <p class="mb-4 text-sm text-muted">
      {{ t("convert.body") }}
    </p>

    <ul class="mb-4 max-h-[46vh] space-y-2 overflow-y-auto">
      <li
        v-for="type in options"
        :key="type.name"
      >
        <button
          type="button"
          class="flex min-h-tap w-full items-center gap-3 rounded-rpos border px-4 py-3 text-start transition duration-200 ease-rpos"
          :class="[
            chosen?.name === type.name
              ? 'border-primary bg-primary/5'
              : 'border-line hover:border-primary/40 hover:bg-background',
            convertible(type) ? '' : 'cursor-not-allowed opacity-50 hover:border-line hover:bg-transparent',
          ]"
          :disabled="!convertible(type)"
          @click="choose(type)"
        >
          <span
            class="grid h-11 w-11 shrink-0 place-items-center rounded-rpos"
            :style="{ backgroundColor: `${type.color ?? '#94A3B8'}1A`, color: type.color ?? undefined }"
          >
            <AppIcon
              :name="(type.icon as never) ?? 'receipt'"
              :size="22"
            />
          </span>

          <span class="min-w-0">
            <span class="block truncate font-semibold">{{ pick(type.title_ar, type.title) }}</span>
            <span
              v-if="!convertible(type)"
              class="block truncate text-xs text-muted"
            >{{ reasonFor(type) }}</span>
          </span>

          <AppIcon
            v-if="chosen?.name === type.name"
            name="check"
            class="ms-auto shrink-0 text-primary"
            :size="20"
          />
        </button>
      </li>
    </ul>

    <p
      v-if="failure"
      role="alert"
      class="mb-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <p
      v-else-if="loading"
      class="mb-4 flex items-center gap-2 text-sm text-muted"
    >
      <AppIcon
        name="refresh"
        class="animate-spin"
        :size="18"
      />
      {{ t("common.loading") }}
    </p>

    <!--
      The two figures, side by side. A conversion that moves the bill is the
      whole reason this preview exists (D-036); one that does not says so, so
      the cashier is not left wondering what changed.
    -->
    <div
      v-else-if="preview"
      class="mb-4 rounded-rpos bg-background p-4"
    >
      <div
        v-if="priceChanged"
        class="flex items-center justify-between gap-3"
      >
        <span class="text-sm text-muted">{{ t("convert.totalNow") }}</span>
        <span class="rpos-numeric text-sm text-muted line-through">{{ money(preview.total_before) }}</span>
      </div>
      <div
        v-if="priceChanged"
        class="mt-1 flex items-center justify-between gap-3"
      >
        <span class="font-semibold">{{ t("convert.totalAfter") }}</span>
        <span class="rpos-numeric text-xl font-bold text-primary">{{ money(preview.total_after) }}</span>
      </div>

      <p
        v-else
        class="text-sm text-muted"
      >
        {{ t("convert.samePrice", { total: money(preview.total_after) }) }}
      </p>

      <p
        v-if="needsTable"
        class="mt-3 flex items-center gap-2 text-sm text-status-reserved"
      >
        <AppIcon
          name="floorPlan"
          :size="18"
        />
        {{ t("convert.needsTable") }}
      </p>
    </div>

    <!-- BR-064 — asked here rather than refused later (FR-2.1a). -->
    <div
      v-if="preview && needsCovers"
      class="mb-4 rounded-rpos bg-background p-4"
    >
      <p class="mb-3 text-sm font-semibold">
        {{ t("covers.title") }}
      </p>
      <div class="flex items-center justify-center gap-4">
        <button
          type="button"
          class="grid h-12 w-12 place-items-center rounded-full bg-surface text-muted transition duration-200 ease-rpos hover:text-primary disabled:opacity-40"
          :disabled="covers <= 1"
          :aria-label="t('picker.qtyLess')"
          @click="covers = Math.max(1, covers - 1)"
        >
          <AppIcon
            name="minus"
            :size="22"
          />
        </button>

        <span class="rpos-numeric w-14 text-center text-2xl font-bold">{{
          formatNumber(covers)
        }}</span>

        <button
          type="button"
          class="grid h-12 w-12 place-items-center rounded-full bg-surface text-muted transition duration-200 ease-rpos hover:text-primary"
          :aria-label="t('picker.qtyMore')"
          @click="covers = covers + 1"
        >
          <AppIcon
            name="plus"
            :size="22"
          />
        </button>
      </div>
    </div>

    <div class="flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.undo") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!preview || loading || busy"
        @click="confirm"
      >
        {{ needsTable ? t("convert.pickTable") : t("convert.confirm") }}
      </button>
    </div>
  </BaseDialog>
</template>
