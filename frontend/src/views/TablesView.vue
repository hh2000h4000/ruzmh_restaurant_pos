<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { getFloorPlan, type FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import BillPicker from "@/components/order/BillPicker.vue";
import TableReadyDialog from "@/components/order/TableReadyDialog.vue";
import { pick, t, timeOnly, tn } from "@/i18n";
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
/** Computed, not a constant: the labels have to follow a language switch. */
const statusLabel = computed<Record<FloorTable["status"], string>>(() => ({
  available: t("table.available"),
  occupied: t("table.occupied"),
  reserved: t("table.reserved"),
  cleaning: t("table.cleaning"),
  inactive: t("table.inactive"),
}));

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

/** The table whose bills the cashier is choosing between (`BR-066`). */
const picking = ref<FloorTable | null>(null);
const readying = ref<FloorTable | null>(null);
const coverCount = ref(2);
const creating = ref(false);

const orderTypeName = route.params.orderType as string;
const orderType = computed(
  () => session.orderTypes.find((type) => type.name === orderTypeName) ?? null,
);

/**
 * The order this screen is seating, when it already exists (D-038).
 *
 * A conversion into a table-service type comes here to pick the table rather
 * than opening a second order. Without this the cashier would end up with two
 * bills for one customer.
 */
const converting = computed(() => (route.query.convert as string | undefined) ?? null);

// --------------------------------------------------------------------------
// The halls (D-040)
// --------------------------------------------------------------------------

/**
 * Every hall in the branch, not only the terminal's own.
 *
 * A restaurant with a men's hall and a family hall usually runs one till at the
 * door for both, so the screen offers them as tabs and the backend judges a
 * table by its branch.
 */
const sections = computed(() => session.data?.sections ?? []);
const activeSection = ref(session.data?.restaurant_section?.name ?? "");

const counts = computed(() => {
  const tally: Record<string, number> = {};
  for (const table of tables.value) {
    tally[table.status] = (tally[table.status] ?? 0) + 1;
  }
  return tally;
});

onMounted(load);

async function load(): Promise<void> {
  const section = activeSection.value || session.data?.restaurant_section?.name;
  if (!section) {
    failure.value = t("tables.noSection");
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

/** Switching halls re-reads the floor; nothing else about the screen changes. */
watch(activeSection, () => {
  chosen.value = null;
  picking.value = null;
  readying.value = null;
  void load();
});

/**
 * FR-5.2 — a free table starts an order, an occupied one opens its bill.
 *
 * With more than one bill on the table (`BR-066`) there is nothing to guess
 * at, so the cashier is asked which. Picking for them is how a waiter adds a
 * round of drinks to the wrong party's bill.
 */
async function onTable(table: FloorTable): Promise<void> {
  const bills = table.orders ?? [];

  if (bills.length > 1) {
    picking.value = table;
    return;
  }

  if (bills.length === 1) {
    await router.push({ name: "order", params: { orderName: bills[0].name } });
    return;
  }

  // A wiped-down table is the one thing a `cleaning` table is waiting to be
  // told; before this it was simply disabled and stayed that way for ever.
  if (table.status === "cleaning") {
    readying.value = table;
    return;
  }

  if (table.status !== "available" && table.status !== "reserved") return;

  chosen.value = table;
  coverCount.value = Math.min(table.capacity || 2, 4) || 2;
}

async function openBill(orderName: string): Promise<void> {
  picking.value = null;
  await router.push({ name: "order", params: { orderName } });
}

async function startOrder(): Promise<void> {
  const table = chosen.value;
  const type = orderType.value;
  if (!table || !type || creating.value) return;

  creating.value = true;
  try {
    // An order already exists: this is a conversion picking its table, not a
    // new sale (D-038).
    if (converting.value) {
      const done = await orders.changeType(type.name, {
        table: table.name,
        coverCount: coverCount.value,
      });

      if (done) {
        await router.replace({ name: "order", params: { orderName: converting.value } });
      } else {
        failure.value = orders.error;
        chosen.value = null;
        await load();
      }
      return;
    }

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
  <main class="mx-auto min-h-0 w-full max-w-5xl overflow-y-auto p-4">
    <header class="mb-4 flex items-center gap-3">
      <RouterLink
        :to="{ name: 'home' }"
        class="rpos-tap inline-flex items-center px-2 text-primary"
      >
        ←
      </RouterLink>
      <div class="flex-1">
        <h1 class="font-semibold">
          {{ t("tables.title") }}
        </h1>
        <p class="text-xs text-muted">
          {{ pick(orderType?.title_ar, orderType?.title) }}
        </p>
      </div>
      <button
        type="button"
        class="rpos-tap rounded-rpos border border-line px-3 text-sm"
        :disabled="loading"
        @click="load"
      >
        🔄 {{ t("action.refresh") }}
      </button>
    </header>

    <!-- One till, every hall (D-040). Hidden when there is only one to show. -->
    <div
      v-if="sections.length > 1"
      class="mb-4 flex flex-wrap gap-2"
      role="tablist"
    >
      <button
        v-for="section in sections"
        :key="section.name"
        type="button"
        role="tab"
        class="min-h-tap rounded-rpos px-4 text-sm font-semibold transition duration-200 ease-rpos"
        :class="
          activeSection === section.name
            ? 'bg-primary text-primary-contrast shadow-card'
            : 'bg-surface text-muted shadow-card hover:text-content'
        "
        :aria-selected="activeSection === section.name"
        @click="activeSection = section.name"
      >
        {{ pick(section.title_ar, section.title) }}
      </button>
    </div>

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
      {{ t("common.loading") }}
    </p>

    <template v-else>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <button
          v-for="table in tables"
          :key="table.name"
          type="button"
          class="flex min-h-[7rem] flex-col items-center justify-center gap-1 rounded-rpos border-2 p-3 disabled:opacity-60"
          :class="STATUS_CLASS[table.status]"
          :disabled="table.status === 'inactive'"
          :aria-label="`${t('card.table', { number: table.table_number })} — ${statusLabel[table.status]}`"
          @click="onTable(table)"
        >
          <span class="rpos-numeric text-2xl font-bold">{{ table.table_number }}</span>
          <span class="text-xs font-medium">{{ statusLabel[table.status] }}</span>

          <span
            v-if="(table.orders ?? []).length"
            class="rpos-numeric text-xs"
          >
            <template v-if="table.orders.length > 1">
              {{ tn("count.bills", table.orders.length) }}
            </template>
            <template v-else>
              {{ timeOnly(table.orders[0].opened_at) }} ·
              {{ tn("count.items", table.orders[0].item_count) }}
            </template>
          </span>
          <span
            v-else-if="table.capacity"
            class="rpos-numeric text-xs opacity-70"
          >
            {{ tn("count.seats", table.capacity) }}
          </span>
        </button>
      </div>

      <p
        v-if="!tables.length"
        class="rounded-rpos bg-surface p-8 text-center text-muted"
      >
        {{ t("tables.empty") }}
      </p>

      <!-- The legend doubles as the counts strip in 06 Screen 5. -->
      <footer class="mt-4 flex flex-wrap gap-3 text-xs">
        <span
          v-for="(label, status) in statusLabel"
          :key="status"
          class="rounded-rpos px-2 py-1"
          :class="STATUS_CLASS[status]"
        >
          {{ label }} ({{ counts[status] ?? 0 }})
        </span>
      </footer>
    </template>

    <BillPicker
      :table="picking"
      @pick="openBill"
      @close="picking = null"
    />

    <TableReadyDialog
      :table="readying"
      @done="
        readying = null;
        void load();
      "
      @close="readying = null"
    />

    <BaseDialog
      :open="Boolean(chosen)"
      :title="t('card.table', { number: chosen?.table_number ?? '' })"
      @close="chosen = null"
    >
      <!-- BR-064 — cover count is mandatory when the order type asks for it. -->
      <template v-if="orderType?.requires_cover_count">
        <label
          for="covers"
          class="mb-1 block text-sm font-medium"
        >{{ t("tables.covers") }}</label>
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
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
          :disabled="creating || (orderType?.requires_cover_count === 1 && coverCount < 1)"
          @click="startOrder"
        >
          {{ creating ? "…" : t("tables.start") }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
