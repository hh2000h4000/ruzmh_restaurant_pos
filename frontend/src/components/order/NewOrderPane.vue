<script setup lang="ts">
import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

/**
 * Start another order without finishing this one (D-042).
 *
 * A customer takes their time paying and the queue behind them does not care.
 * Tapping a type here opens a fresh order and leaves the current one exactly
 * where it is — which needs no "held orders" feature, because an order has been
 * a real `Restaurant Order` on the server since the moment it was created. The
 * cashier finds it again under **الطلبات**.
 *
 * The types are data, filtered by role, terminal and branch before they arrive
 * (FR-1.3). Nothing here is hardcoded — including whether a type seats people:
 * that is `requires_table` on the type, because plenty of restaurants run
 * dine-in with no table plan at all and the customer simply takes a seat.
 */
/**
 * The table this pane is choosing a type for, when it was reached from the
 * floor (FR-2.1a). `null` on the ordinary "start another order" path.
 */
defineProps<{ seating?: string | null }>();

const emit = defineEmits<{ open: [orderType: OrderType] }>();

const session = useSessionStore();

/**
 * An order type's icon is configured, not guessed — the same rule the till
 * screen's column follows, so the two never disagree about what a type looks
 * like.
 */
const NAMES = new Set<string>([
  "plane",
  "mobile",
  "card",
  "users",
  "hanger",
  "truck",
  "home",
  "bag",
  "receipt",
  "document",
]);

function icon(orderType: OrderType): IconName | null {
  const configured = (orderType.icon ?? "").trim();
  if (NAMES.has(configured)) return configured as IconName;
  if (configured) return null;

  if (orderType.requires_table) return "home";
  if (orderType.customer_mode === "required") return "users";
  return "bag";
}

function glyph(orderType: OrderType): string | null {
  const configured = (orderType.icon ?? "").trim();
  return NAMES.has(configured) ? null : configured || null;
}

function subtitle(orderType: OrderType): string {
  if (!available(orderType)) return t("order.customerPending");
  if (orderType.requires_table) return t("type.hintTable");
  return t("type.hintQuick");
}

/**
 * A type that needs a customer cannot be opened until the customer picker
 * exists (FR-2.1 step 4).
 *
 * Shown disabled with the reason rather than hidden: the manager configured it,
 * so a cashier who cannot find it will ask whether the system is broken. The
 * server refuses it either way — this only saves the cashier a raw error.
 */
function available(orderType: OrderType): boolean {
  return orderType.customer_mode !== "required";
}
</script>

<template>
  <section
    class="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] rounded-rpos bg-surface p-5 shadow-card"
  >
    <div class="mb-4">
      <h2 class="flex items-center gap-2 text-xl font-bold">
        <AppIcon
          :name="seating ? 'floorPlan' : 'plus'"
          :size="24"
        />
        {{ seating ? t("tables.seatWhat", { number: seating }) : t("home.newOrder") }}
      </h2>
      <p class="mt-1 text-sm text-muted">
        {{ seating ? t("tables.seatHint") : t("nav.newHint") }}
      </p>
    </div>

    <div class="min-h-0 overflow-y-auto">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-3">
        <button
          v-for="orderType in session.orderTypes"
          :key="orderType.name"
          type="button"
          class="flex h-[94px] items-center gap-4 rounded-rpos border border-line bg-surface px-4 text-start transition duration-200 ease-rpos enabled:hover:-translate-y-px enabled:hover:border-primary/40 enabled:hover:shadow-card disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!available(orderType)"
          @click="emit('open', orderType)"
        >
          <span class="relative grid h-16 w-16 shrink-0 place-items-center overflow-hidden rounded-full">
            <span
              class="absolute inset-0 opacity-10"
              :style="{ backgroundColor: orderType.color ?? undefined }"
            />
            <AppIcon
              v-if="icon(orderType)"
              :name="icon(orderType)!"
              :size="30"
              :style="{ color: orderType.color ?? undefined }"
            />
            <span
              v-else
              class="text-2xl"
            >{{ glyph(orderType) }}</span>
          </span>

          <span class="min-w-0">
            <span class="block truncate text-lg font-bold">
              {{ pick(orderType.title_ar, orderType.title) }}
            </span>
            <span class="block truncate text-sm text-muted">{{ subtitle(orderType) }}</span>
          </span>
        </button>
      </div>

      <p
        v-if="!session.orderTypes.length"
        class="rounded-rpos bg-background p-8 text-center text-muted"
      >
        {{ t("home.noOrderTypes") }}
      </p>
    </div>
  </section>
</template>
