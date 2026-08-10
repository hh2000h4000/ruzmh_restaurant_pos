<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getFloorPlan, type FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import { useOrderStore } from "@/stores/order";
import { useSessionStore } from "@/stores/session";

/**
 * Table selection for a dine-in order (FR-5.2).
 *
 * A list, not the canvas floor plan — that is Phase 4. It reads the same
 * `get_floor_plan` payload the canvas will, so the drawing arrives later
 * without an API change.
 *
 * Status colours come from the fixed palette and are never themed (FR-15.5):
 * staff read green as "free" and act on it.
 */
const STATUS_LABEL: Record<FloorTable["status"], string> = {
  available: "فارغة",
  occupied: "مشغولة",
  reserved: "محجوزة",
  cleaning: "تنظيف",
  inactive: "خارج الخدمة",
};

const STATUS_CLASS: Record<FloorTable["status"], string> = {
  available: "border-status-available bg-status-available/10 text-status-available",
  occupied: "border-status-occupied bg-status-occupied/10 text-status-occupied",
  reserved: "border-status-reserved bg-status-reserved/10 text-status-reserved",
  cleaning: "border-status-cleaning bg-status-cleaning/10 text-status-cleaning",
  inactive: "border-status-inactive bg-status-inactive/10 text-status-inactive",
};

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const orders = useOrderStore();

const tables = ref<FloorTable[]>([]);
const loading = ref(true);
const failure = ref<string | null>(null);

const chosen = ref<FloorTable | null>(null);
const coverCount = ref(2);
const creating = ref(false);

const orderTypeName = route.params.orderType as string;
const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orderTypeName) ?? null,
);

const counts = computed(() => {
  const tally: Record<string, number> = {};
  for (const table of tables.value) {
    tally[table.status] = (tally[table.status] ?? 0) + 1;
  }
  return tally;
});

onMounted(load);

async function load(): Promise<void> {
  const section = session.data?.restaurant_section?.name;
  if (!section) {
    failure.value = "هذا الجهاز غير مرتبط بقسم.";
    loading.value = false;
    return;
  }

  loading.value = true;
  try {
    const plan = await getFloorPlan(section);
    tables.value = plan.tables;
    failure.value = null;
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

/** FR-5.2 — free table starts an order, occupied table opens the one it has. */
async function onTable(table: FloorTable): Promise<void> {
  if (table.current_order) {
    await router.push({ name: "order", params: { orderName: table.current_order } });
    return;
  }

  if (table.status !== "available" && table.status !== "reserved") return;

  chosen.value = table;
  coverCount.value = Math.min(table.capacity || 2, 4) || 2;
}

async function startOrder(): Promise<void> {
  const table = chosen.value;
  const type = orderType.value;
  if (!table || !type || creating.value) return;

  creating.value = true;
  try {
    const created = await orders.create({
      order_type: type.name,
      pos_profile: session.profile!.name,
      table: table.name,
      cover_count: coverCount.value,
    });

    if (created) {
      await router.replace({ name: "order", params: { orderName: created } });
    } else {
      failure.value = orders.error;
      chosen.value = null;
      await load();
    }
  } finally {
    creating.value = false;
  }
}
</script>

<template>
  <main class="mx-auto max-w-5xl p-4">
    <header class="mb-4 flex items-center gap-3">
      <RouterLink
        :to="{ name: 'home' }"
        class="rpos-tap inline-flex items-center px-2 text-primary"
      >
        ←
      </RouterLink>
      <div class="flex-1">
        <h1 class="font-semibold">
          {{ session.data?.restaurant_section?.title_ar ?? "الطاولات" }}
        </h1>
        <p class="text-xs text-muted">
          {{ orderType?.title_ar }}
        </p>
      </div>
      <button
        type="button"
        class="rpos-tap rounded-rpos border border-line px-3 text-sm"
        :disabled="loading"
        @click="load"
      >
        🔄 تحديث
      </button>
    </header>

    <p
      v-if="failure"
      role="alert"
      class="rounded-rpos bg-danger/10 p-4 text-danger"
    >
      {{ failure }}
    </p>

    <p
      v-else-if="loading"
      class="p-8 text-center text-muted"
    >
      جارٍ التحميل…
    </p>

    <template v-else>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <button
          v-for="table in tables"
          :key="table.name"
          type="button"
          class="flex min-h-[7rem] flex-col items-center justify-center gap-1 rounded-rpos border-2 p-3 disabled:opacity-60"
          :class="STATUS_CLASS[table.status]"
          :disabled="table.status === 'inactive' || table.status === 'cleaning'"
          :aria-label="`طاولة ${table.table_number} — ${STATUS_LABEL[table.status]}`"
          @click="onTable(table)"
        >
          <span class="rpos-numeric text-2xl font-bold">{{ table.table_number }}</span>
          <span class="text-xs font-medium">{{ STATUS_LABEL[table.status] }}</span>

          <span
            v-if="table.current_order"
            class="rpos-numeric text-xs"
          >
            {{ table.order_minutes }} د · {{ table.item_count }} صنف
          </span>
          <span
            v-else-if="table.capacity"
            class="rpos-numeric text-xs opacity-70"
          >
            {{ table.capacity }} كراسي
          </span>
        </button>
      </div>

      <p
        v-if="!tables.length"
        class="rounded-rpos bg-surface p-8 text-center text-muted"
      >
        لا توجد طاولات في هذا القسم.
      </p>

      <!-- The legend doubles as the counts strip in 06 Screen 5. -->
      <footer class="mt-4 flex flex-wrap gap-3 text-xs">
        <span
          v-for="(label, status) in STATUS_LABEL"
          :key="status"
          class="rounded-rpos px-2 py-1"
          :class="STATUS_CLASS[status]"
        >
          {{ label }} ({{ counts[status] ?? 0 }})
        </span>
      </footer>
    </template>

    <BaseDialog
      :open="Boolean(chosen)"
      :title="`طاولة ${chosen?.table_number ?? ''}`"
      @close="chosen = null"
    >
      <!-- BR-064 — cover count is mandatory when the order type asks for it. -->
      <template v-if="orderType?.requires_cover_count">
        <label
          for="covers"
          class="mb-1 block text-sm font-medium"
        >عدد الضيوف</label>
        <input
          id="covers"
          v-model.number="coverCount"
          type="number"
          min="1"
          class="rpos-numeric mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-center text-xl"
        >
      </template>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="chosen = null"
        >
          تراجع
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
          :disabled="creating || (orderType?.requires_cover_count === 1 && coverCount < 1)"
          @click="startOrder"
        >
          {{ creating ? "…" : "فتح الطلب" }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
