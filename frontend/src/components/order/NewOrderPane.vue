<script setup lang="ts">
import { computed } from "vue";

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
 *
 * **Names, and nothing to explain them** (`D-385`). A heading, a hint, an icon
 * and a line under each type saying where it leads: the cashier knows what
 * «محلي» and «طاولات» mean, and was reading four things to tap one. One column
 * while there are a handful, two once there are more.
 */
const emit = defineEmits<{ open: [orderType: OrderType] }>();

const session = useSessionStore();

/** Up to four sit in one column; a fifth starts a second. */
const twoColumns = computed(() => session.orderTypes.length > 4);

</script>

<template>
  <div class="max-h-[60vh] overflow-y-auto pt-1">
    <div
      class="grid gap-3"
      :class="twoColumns ? 'grid-cols-2' : 'grid-cols-1'"
    >
      <button
        v-for="orderType in session.orderTypes"
        :key="orderType.name"
        type="button"
        class="min-h-14 truncate rounded bg-surface px-4 text-lg font-medium transition duration-100 ease-rpos active:bg-primary/10"
        @click="emit('open', orderType)"
      >
        {{ pick(orderType.title_ar, orderType.title) }}
      </button>
    </div>

    <p
      v-if="!session.orderTypes.length"
      class="rounded bg-surface p-8 text-center text-subtle"
    >
      {{ t("home.noOrderTypes") }}
    </p>
  </div>
</template>
