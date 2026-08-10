<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import { useSessionStore } from "@/stores/session";
import type { OrderType } from "@/types/session";

const session = useSessionStore();
const router = useRouter();

const sectionTitle = computed(
  () => session.data?.restaurant_section?.title_ar ?? session.branch ?? "",
);

/**
 * FR-1.3 — the backend already filtered these by role, terminal and branch, so
 * the screen renders what it is given rather than filtering again. A second
 * filter here could disagree with the one that accepts the order.
 */
const orderTypes = computed(() => session.orderTypes);

function open(orderType: OrderType): void {
  void router.push({ name: "new-order", params: { orderType: orderType.name } });
}
</script>

<template>
  <main class="mx-auto max-w-6xl p-4">
    <header class="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">{{ sectionTitle }}</h1>
        <p class="text-sm text-muted">
          {{ session.data?.pos_profile.name }}
        </p>
      </div>

      <div
        v-if="session.hasOpenShift"
        class="rounded-rpos bg-status-available/10 px-3 py-1.5 text-sm text-status-available"
      >
        الوردية مفتوحة
      </div>
      <div v-else class="rounded-rpos bg-status-reserved/10 px-3 py-1.5 text-sm text-status-reserved">
        لا توجد وردية مفتوحة
      </div>
    </header>

    <!-- BR-044: no order can be created without an open shift, so say so
         instead of showing buttons that will be refused. -->
    <section v-if="!session.hasOpenShift" class="rounded-rpos bg-surface p-6 text-center">
      <p class="mb-4">افتح وردية قبل استقبال الطلبات.</p>
      <RouterLink
        :to="{ name: 'open-shift' }"
        class="inline-flex min-h-tap items-center rounded-rpos bg-primary px-6 text-primary-contrast"
      >
        فتح وردية
      </RouterLink>
    </section>

    <section v-else>
      <h2 class="mb-3 text-sm font-medium text-muted">افتح طلباً جديداً</h2>

      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <button
          v-for="orderType in orderTypes"
          :key="orderType.name"
          type="button"
          class="flex min-h-[7rem] min-w-tap flex-col items-center justify-center gap-2 rounded-rpos bg-surface p-4 shadow-sm transition hover:shadow focus:outline-none focus:ring-2 focus:ring-primary"
          :style="orderType.color ? { borderBottom: `4px solid ${orderType.color}` } : undefined"
          :aria-label="orderType.title_ar"
          @click="open(orderType)"
        >
          <span v-if="orderType.icon" class="text-3xl" aria-hidden="true">{{ orderType.icon }}</span>
          <span class="text-base font-medium">{{ orderType.title_ar }}</span>
        </button>
      </div>

      <p v-if="!orderTypes.length" class="rounded-rpos bg-surface p-6 text-center text-muted">
        لا توجد أنواع طلبات متاحة على هذا الجهاز.
      </p>
    </section>
  </main>
</template>
