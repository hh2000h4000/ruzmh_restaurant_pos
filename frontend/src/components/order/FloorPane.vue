<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { getFloorPlan, type FloorTable } from "@/api/table";
import AppIcon from "@/components/AppIcon.vue";
import { pick, t, tn } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * The floor, inside the order screen (D-042).
 *
 * A list, not the canvas floor plan — that is Phase 4. It reads the same
 * `get_floor_plan` payload the canvas will, so the drawing arrives later
 * without an API change.
 *
 * Every hall in the branch is offered as a tab, not only the terminal's own
 * (D-040): one till at the door usually serves both the men's hall and the
 * family hall.
 *
 * Status colours come from the fixed palette and are never themed (FR-15.5):
 * staff read green as "free" and act on it.
 */
const emit = defineEmits<{
  /** A free table the cashier wants to seat. */
  seat: [table: FloorTable];
  /** A table that already has an order; open that order instead. */
  open: [orderName: string];
}>();

const session = useSessionStore();

const tables = ref<FloorTable[]>([]);
const loading = ref(true);
const failure = ref<string | null>(null);

const sections = computed(() => session.data?.sections ?? []);
const activeSection = ref(session.data?.restaurant_section?.name ?? "");

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

onMounted(load);
watch(activeSection, load);

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

/** FR-5.2 — an occupied table opens the order it has; a free one seats this one. */
function onTable(table: FloorTable): void {
  if (table.current_order) {
    emit("open", table.current_order);
    return;
  }

  if (table.status !== "available" && table.status !== "reserved") return;
  emit("seat", table);
}

defineExpose({ reload: load });
</script>

<template>
  <section
    class="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] rounded-rpos bg-surface p-5 shadow-card"
  >
    <div>
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 class="flex items-center gap-2 text-xl font-bold">
          <AppIcon
            name="floorPlan"
            :size="24"
          />
          {{ t("tables.title") }}
        </h2>

        <button
          type="button"
          class="flex min-h-tap items-center gap-2 rounded-rpos bg-background px-4 text-sm font-semibold text-muted transition duration-200 ease-rpos hover:text-content disabled:opacity-40"
          :disabled="loading"
          @click="load"
        >
          <AppIcon
            name="refresh"
            :size="18"
            :class="loading ? 'animate-spin' : ''"
          />
          {{ t("action.refresh") }}
        </button>
      </div>

      <!-- One till, every hall (D-040). Hidden when there is only one. -->
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
              : 'bg-background text-muted hover:text-content'
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
        class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ failure }}
      </p>
    </div>

    <div class="min-h-0 overflow-y-auto">
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
        <button
          v-for="table in tables"
          :key="table.name"
          type="button"
          class="flex min-h-[7rem] flex-col items-center justify-center gap-1 rounded-rpos border-2 p-3 transition duration-200 ease-rpos hover:-translate-y-px hover:shadow-card disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-none"
          :class="STATUS_CLASS[table.status]"
          :disabled="table.status === 'inactive' || table.status === 'cleaning'"
          :aria-label="`${t('card.table', { number: table.table_number })} — ${statusLabel[table.status]}`"
          @click="onTable(table)"
        >
          <span class="rpos-numeric text-2xl font-bold">{{ table.table_number }}</span>
          <span class="text-xs font-medium">{{ statusLabel[table.status] }}</span>

          <span
            v-if="table.current_order"
            class="rpos-numeric text-xs"
          >
            {{ tn("count.minutes", table.order_minutes ?? 0) }} ·
            {{ tn("count.items", table.item_count ?? 0) }}
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
        v-if="!tables.length && !loading"
        class="rounded-rpos bg-background p-8 text-center text-muted"
      >
        {{ t("tables.empty") }}
      </p>
    </div>
  </section>
</template>
