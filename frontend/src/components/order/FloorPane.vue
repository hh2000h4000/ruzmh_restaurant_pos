<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { getFloorPlan, type FloorTable } from "@/api/table";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import BillPicker from "@/components/order/BillPicker.vue";
import { pick, t, timeOnly, tn } from "@/i18n";
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
  /** The party that booked this table has arrived (`FR-14.3`). */
  seatBooking: [reservation: string, tableNumber: string];
}>();

/**
 * A held table the cashier tapped, waiting for them to say who is sitting at it
 * (`D-191`).
 *
 * **A question, not a wall.** The server does not refuse a walk-in here — the
 * party may have cancelled by phone, or the host may know the walk-in is only
 * having a coffee — so neither does the screen. What it must not do is let the
 * cashier seat a stranger on a table held for eight o'clock without being told.
 */
const booking = ref<FloorTable | null>(null);

function seatTheBooking(): void {
  const table = booking.value;
  booking.value = null;
  if (table?.reservation) emit("seatBooking", table.reservation.name, table.table_number);
}

function seatSomebodyElse(): void {
  const table = booking.value;
  booking.value = null;
  if (table) emit("seat", table);
}

const session = useSessionStore();

const tables = ref<FloorTable[]>([]);
const loading = ref(true);

/** The table whose bills the cashier is choosing between (`BR-066`). */
const picking = ref<FloorTable | null>(null);
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

/**
 * FR-5.2 — an occupied table opens its bill; a free one seats this order.
 *
 * More than one bill on the table (`BR-066`) is a question, not a guess.
 */
function onTable(table: FloorTable): void {
  const bills = table.orders ?? [];

  if (bills.length > 1) {
    picking.value = table;
    return;
  }

  if (bills.length === 1) {
    emit("open", bills[0].name);
    return;
  }

  if (table.status !== "available" && table.status !== "reserved") return;

  if (table.reservation?.held) {
    booking.value = table;
    return;
  }

  emit("seat", table);
}

function openBill(orderName: string): void {
  picking.value = null;
  emit("open", orderName);
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

          <!-- The day's next booking, held or not (`D-191`). On an occupied
               table it is the host's warning that the table is due back. -->
          <span
            v-if="table.reservation"
            data-booking
            class="rpos-numeric flex items-center gap-1 text-xs font-semibold text-status-reserved"
          >
            <AppIcon
              name="calendar"
              :size="12"
            />
            {{ t("table.booking", { time: table.reservation.time, count: table.reservation.party_size }) }}
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
    <BillPicker
      :table="picking"
      @pick="openBill"
      @close="picking = null"
    />

    <BaseDialog
      :open="booking !== null"
      :title="booking ? t('reservations.heldTitle', { number: booking.table_number }) : ''"
      @close="booking = null"
    >
      <p
        v-if="booking?.reservation"
        class="mb-4 text-sm text-muted"
      >
        {{
          t("reservations.heldBody", {
            name: booking.reservation.guest,
            time: booking.reservation.time,
            count: booking.reservation.party_size,
          })
        }}
      </p>
      <div class="flex flex-col gap-2">
        <button
          type="button"
          data-seat-booking
          class="min-h-tap rounded-rpos bg-primary px-4 font-semibold text-primary-contrast"
          @click="seatTheBooking"
        >
          {{ t("reservations.seatBooking") }}
        </button>
        <button
          type="button"
          data-seat-other
          class="min-h-tap rounded-rpos border border-line px-4 font-medium"
          @click="seatSomebodyElse"
        >
          {{ t("reservations.seatOther") }}
        </button>
      </div>
    </BaseDialog>
  </section>
</template>
