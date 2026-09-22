<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import {
  cancelReservation,
  listReservations,
  markNoShow,
  type Reservation,
} from "@/api/reservation";
import AppIcon from "@/components/AppIcon.vue";
import ReasonDialog from "@/components/order/ReasonDialog.vue";
import ReservationDialog from "@/components/order/ReservationDialog.vue";
import { t, type MessageKey } from "@/i18n";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * A day's bookings, in the order the guests arrive (`FR-14`, `D-191`).
 *
 * A pane of the one till screen, beside the floor and the orders (`D-055`),
 * not a screen of its own: the host who takes a booking at the counter is the
 * cashier, between two sales.
 *
 * **What the server says, not what this device's clock thinks.** Whether a
 * booking is holding its table, or is late and has let it go, comes back as
 * `phase`, worked out from the branch's turn time and grace period. A tablet
 * with its clock five minutes out would otherwise tell the host a table was
 * free that the floor was still holding.
 *
 * **Seating is not done here.** It is handed up, to the one place the till
 * decides which kind of order to open on a table — so a booking seated from
 * this list and one seated from the floor open the same bill the same way.
 */
const emit = defineEmits<{ seat: [reservation: Reservation] }>();

const session = useSessionStore();
const connection = useConnectionStore();

/** `YYYY-MM-DD`, in this device's own calendar. */
function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

const today = isoDay(new Date());
const day = ref(today);
const rows = ref<Reservation[]>([]);
const loading = ref(false);
const failure = ref<string | null>(null);
const warnings = ref<string[]>([]);

const editing = ref<Reservation | null>(null);
const creating = ref(false);
const cancelling = ref<Reservation | null>(null);
const busy = ref(false);

const isToday = computed(() => day.value === today);

onMounted(load);
watch(day, load);
watch(
  () => connection.isOnline,
  (online) => {
    if (online) void load();
  },
);

async function load(): Promise<void> {
  if (!connection.isOnline) {
    failure.value = t("reservations.offline");
    return;
  }

  loading.value = true;
  try {
    rows.value = await listReservations(session.profile!.name, day.value);
    failure.value = null;
  } catch (cause) {
    failure.value = message(cause);
  } finally {
    loading.value = false;
  }
}

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

function moveDay(days: number): void {
  const next = new Date(`${day.value}T12:00:00`);
  next.setDate(next.getDate() + days);
  day.value = isoDay(next);
}

function expected(row: Reservation): boolean {
  return row.status === "pending" || row.status === "confirmed";
}

/** The one word the host reads on a row. */
function standing(row: Reservation): string {
  if (expected(row) && row.phase) return t(`reservations.phase.${row.phase}` as MessageKey);
  return t(`reservations.status.${row.status}` as MessageKey);
}

/** Only today's, and only with a table: the server refuses anything else. */
function maySeat(row: Reservation): boolean {
  return expected(row) && isToday.value && Boolean(row.table);
}

function onSaved(said: string[]): void {
  warnings.value = said;
  creating.value = false;
  editing.value = null;
  void load();
}

async function act(run: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  try {
    await run();
    failure.value = null;
  } catch (cause) {
    failure.value = message(cause);
  } finally {
    busy.value = false;
    await load();
  }
}

function confirmCancel(reason: string): void {
  const row = cancelling.value;
  cancelling.value = null;
  if (row) void act(() => cancelReservation(row.name, reason));
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
            name="calendar"
            :size="24"
          />
          {{ t("reservations.title") }}
        </h2>

        <button
          type="button"
          class="flex min-h-tap items-center gap-2 rounded-rpos bg-primary px-4 text-sm font-semibold text-primary-contrast disabled:opacity-40"
          :disabled="!connection.isOnline"
          @click="creating = true"
        >
          <AppIcon
            name="plus"
            :size="18"
          />
          {{ t("reservations.new") }}
        </button>
      </div>

      <div class="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          class="min-h-tap rounded-rpos bg-background px-3 text-sm text-muted hover:text-content"
          :aria-label="t('reservations.previous')"
          @click="moveDay(-1)"
        >
          <span class="rpos-flip">→</span>
        </button>
        <input
          v-model="day"
          type="date"
          class="rpos-numeric min-h-tap rounded-rpos border border-line bg-background px-3 text-sm"
        >
        <button
          type="button"
          class="min-h-tap rounded-rpos bg-background px-3 text-sm text-muted hover:text-content"
          :aria-label="t('reservations.next')"
          @click="moveDay(1)"
        >
          <span class="rpos-flip">←</span>
        </button>
        <button
          v-if="!isToday"
          type="button"
          class="min-h-tap rounded-rpos bg-background px-3 text-sm font-semibold text-primary"
          @click="day = today"
        >
          {{ t("reservations.today") }}
        </button>
      </div>

      <p
        v-if="failure"
        role="alert"
        class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ failure }}
      </p>

      <div
        v-if="warnings.length"
        class="mb-3 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
      >
        <p class="font-medium">
          {{ t("reservations.warned") }}
        </p>
        <p
          v-for="line in warnings"
          :key="line"
        >
          {{ line }}
        </p>
      </div>
    </div>

    <div class="min-h-0 overflow-y-auto">
      <ul class="flex flex-col gap-2">
        <li
          v-for="row in rows"
          :key="row.name"
          class="flex flex-wrap items-center gap-3 rounded-rpos border border-line bg-background p-3"
          :class="expected(row) ? '' : 'opacity-60'"
        >
          <span class="rpos-numeric w-14 shrink-0 text-lg font-bold">{{ row.reservation_time }}</span>

          <div class="min-w-0 flex-1">
            <p class="truncate font-semibold">
              {{ row.customer_name }}
              <span class="text-sm font-normal text-muted">
                · {{ t("reservations.guests", { count: row.party_size }) }}
                · {{ row.table_number ? t("card.table", { number: row.table_number }) : t("reservations.noTable") }}
              </span>
            </p>
            <p class="flex flex-wrap gap-x-3 text-xs text-muted">
              <span
                dir="ltr"
                class="rpos-numeric"
              >{{ row.phone }}</span>
              <span v-if="row.notes">{{ row.notes }}</span>
              <span v-if="row.created_by_name">{{ t("reservations.takenBy", { name: row.created_by_name }) }}</span>
              <span v-if="row.auto_no_show">{{ t("reservations.automatic") }}</span>
              <span v-if="row.cancel_reason">{{ row.cancel_reason }}</span>
            </p>
          </div>

          <span
            class="rounded-full px-3 py-1 text-xs font-medium"
            :class="
              row.phase === 'held'
                ? 'bg-status-reserved/15 text-status-reserved'
                : row.phase === 'late'
                  ? 'bg-danger/10 text-danger'
                  : 'bg-surface text-muted'
            "
          >{{ standing(row) }}</span>

          <div
            v-if="expected(row)"
            class="flex flex-wrap gap-2"
          >
            <button
              v-if="maySeat(row)"
              type="button"
              data-seat
              class="min-h-tap rounded-rpos bg-primary px-3 text-sm font-semibold text-primary-contrast disabled:opacity-40"
              :disabled="busy || !connection.isOnline"
              @click="emit('seat', row)"
            >
              {{ t("reservations.seat") }}
            </button>
            <button
              type="button"
              class="min-h-tap rounded-rpos border border-line px-3 text-sm"
              :disabled="busy || !connection.isOnline"
              @click="editing = row"
            >
              {{ t("reservations.edit") }}
            </button>
            <button
              v-if="row.phase === 'late'"
              type="button"
              data-no-show
              class="min-h-tap rounded-rpos border border-line px-3 text-sm"
              :disabled="busy || !connection.isOnline"
              @click="act(() => markNoShow(row.name))"
            >
              {{ t("reservations.noShow") }}
            </button>
            <button
              type="button"
              data-cancel
              class="min-h-tap rounded-rpos border border-danger px-3 text-sm text-danger"
              :disabled="busy || !connection.isOnline"
              @click="cancelling = row"
            >
              {{ t("reservations.cancel") }}
            </button>
          </div>
        </li>
      </ul>

      <p
        v-if="!rows.length && !loading && !failure"
        class="rounded-rpos bg-background p-8 text-center text-muted"
      >
        {{ t("reservations.empty") }}
      </p>
      <p
        v-else-if="loading && !rows.length"
        class="p-8 text-center text-muted"
      >
        {{ t("common.loading") }}
      </p>
    </div>

    <ReservationDialog
      :open="creating || editing !== null"
      :reservation="editing"
      :date="day"
      @close="creating = false; editing = null"
      @saved="onSaved"
    />

    <ReasonDialog
      :open="cancelling !== null"
      :title="t('reservations.cancelTitle')"
      :explain="
        cancelling
          ? t('reservations.cancelExplain', {
            name: cancelling.customer_name,
            time: cancelling.reservation_time,
            count: cancelling.party_size,
          })
          : ''
      "
      :placeholder="t('reservations.cancelPlaceholder')"
      :confirm="t('reservations.cancel')"
      :busy="busy"
      scope="cancel_reason"
      @confirm="confirmCancel"
      @close="cancelling = null"
    />
  </section>
</template>
