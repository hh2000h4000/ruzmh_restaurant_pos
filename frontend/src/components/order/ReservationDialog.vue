<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { searchCustomers } from "@/api/customer";
import { saveReservation, type Reservation } from "@/api/reservation";
import { getFloorPlan, type FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Take a booking, or change one (`FR-14.1`, `D-191`).
 *
 * **The number first**, as everywhere a guest is identified (`D-050`). The
 * same search the customer box runs looks it up while it is typed, and a
 * regular's name fills itself in; the server links the record on save. Nobody
 * is created: a booking is not a reason to file a person.
 *
 * **Every hall's tables**, because one host takes bookings for the whole
 * branch (`D-040`). The table is optional — a booking can be taken by time and
 * party and given a table when the evening's plan is clearer.
 *
 * What the server refuses — a second booking on a table within one turn, a
 * time already gone — comes back as its own sentence and stays on the form,
 * so the host changes the time instead of retyping everything.
 */
const props = defineProps<{
  open: boolean;
  /** The booking being changed, or nothing for a new one. */
  reservation?: Reservation | null;
  /** The day the list is showing — a new booking starts on it. */
  date: string;
}>();

const emit = defineEmits<{ close: []; saved: [warnings: string[]] }>();

const session = useSessionStore();

const phone = ref("");
const name = ref("");
const party = ref(2);
const day = ref("");
const time = ref("20:00");
const table = ref<string | null>(null);
const notes = ref("");

const tables = ref<FloorTable[]>([]);
const known = ref<string | null>(null);
const busy = ref(false);
const error = ref<string | null>(null);

const canSave = computed(
  () =>
    !busy.value &&
    Boolean(name.value.trim()) &&
    Boolean(phone.value.trim()) &&
    party.value >= 1 &&
    Boolean(day.value) &&
    Boolean(time.value),
);

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;

    const booking = props.reservation;
    phone.value = booking?.phone ?? "";
    name.value = booking?.customer_name ?? "";
    party.value = booking?.party_size ?? 2;
    day.value = booking?.reservation_date ?? props.date;
    time.value = booking?.reservation_time ?? "20:00";
    table.value = booking?.table ?? null;
    notes.value = booking?.notes ?? "";
    known.value = null;
    error.value = null;

    await loadTables();
  },
);

async function loadTables(): Promise<void> {
  const sections = session.data?.sections ?? [];
  try {
    const plans = await Promise.all(sections.map((section) => getFloorPlan(section.name)));
    tables.value = plans.flatMap((plan) => plan.tables).filter((row) => row.status !== "inactive");
  } catch {
    // A booking can still be taken without a table; say nothing louder.
    tables.value = [];
  }
}

let timer: ReturnType<typeof setTimeout> | undefined;

// Nine digits is a whole Saudi mobile without its prefix — the point where a
// search stops matching half the database.
watch(phone, (value) => {
  clearTimeout(timer);
  known.value = null;
  if (value.replace(/\D/g, "").length < 9) return;

  timer = setTimeout(async () => {
    try {
      const [found] = await searchCustomers({ phone: value });
      if (!found) return;
      known.value = found.customer_name;
      if (!name.value.trim()) name.value = found.customer_name;
    } catch {
      // The lookup is a convenience; the booking does not depend on it.
    }
  }, 300);
});

async function save(): Promise<void> {
  if (!canSave.value) return;

  busy.value = true;
  error.value = null;
  try {
    const result = await saveReservation(session.profile!.name, {
      name: props.reservation?.name,
      customer_name: name.value.trim(),
      phone: phone.value.trim(),
      party_size: party.value,
      reservation_date: day.value,
      reservation_time: time.value.length === 5 ? `${time.value}:00` : time.value,
      table: table.value,
      notes: notes.value.trim() || null,
    });
    emit("saved", result.warnings);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="reservation ? t('reservations.edit') : t('reservations.new')"
    @close="emit('close')"
  >
    <form
      class="flex flex-col gap-3"
      @submit.prevent="save"
    >
      <label class="flex flex-col gap-1 text-sm">
        <span class="font-medium">{{ t("reservations.phone") }}</span>
        <input
          v-model="phone"
          type="tel"
          dir="ltr"
          inputmode="tel"
          class="rpos-numeric min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
        >
        <span
          v-if="known"
          class="text-xs text-status-available"
        >{{ t("reservations.known", { name: known }) }}</span>
      </label>

      <label class="flex flex-col gap-1 text-sm">
        <span class="font-medium">{{ t("reservations.name") }}</span>
        <input
          v-model="name"
          type="text"
          class="min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
        >
      </label>

      <div class="grid grid-cols-3 gap-3">
        <label class="flex flex-col gap-1 text-sm">
          <span class="font-medium">{{ t("reservations.party") }}</span>
          <input
            v-model.number="party"
            type="number"
            min="1"
            class="rpos-numeric min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
          >
        </label>
        <label class="flex flex-col gap-1 text-sm">
          <span class="font-medium">{{ t("reservations.date") }}</span>
          <input
            v-model="day"
            type="date"
            class="rpos-numeric min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
          >
        </label>
        <label class="flex flex-col gap-1 text-sm">
          <span class="font-medium">{{ t("reservations.time") }}</span>
          <input
            v-model="time"
            type="time"
            class="rpos-numeric min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
          >
        </label>
      </div>

      <label class="flex flex-col gap-1 text-sm">
        <span class="font-medium">{{ t("reservations.table") }}</span>
        <select
          v-model="table"
          class="min-h-tap rounded-rpos border border-line bg-background px-3 outline-none focus:border-primary"
        >
          <option :value="null">
            {{ t("reservations.noTable") }}
          </option>
          <option
            v-for="row in tables"
            :key="row.name"
            :value="row.name"
          >
            {{ t("card.table", { number: row.table_number }) }} · {{ t("reservations.guests", { count: row.capacity }) }}
          </option>
        </select>
      </label>

      <label class="flex flex-col gap-1 text-sm">
        <span class="font-medium">{{ t("reservations.notes") }}</span>
        <textarea
          v-model="notes"
          rows="2"
          class="rounded-rpos border border-line bg-background px-3 py-2 outline-none focus:border-primary"
        />
      </label>

      <p
        v-if="error"
        role="alert"
        class="rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ error }}
      </p>

      <button
        type="submit"
        class="min-h-tap rounded-rpos bg-primary px-4 font-semibold text-primary-contrast disabled:opacity-50"
        :disabled="!canSave"
      >
        {{ busy ? "…" : t("reservations.save") }}
      </button>
    </form>
  </BaseDialog>
</template>
