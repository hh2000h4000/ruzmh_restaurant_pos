<script setup lang="ts">
/**
 * Who is at work, and for how long (`FR-8.4`, `D-136`).
 *
 * **The half that makes recording attendance worth anything.** Punches nobody
 * at the restaurant can read are a table only payroll opens, months later, when
 * the argument about a Tuesday is already lost. A manager standing at the till
 * has no ERPNext desk in kiosk mode, so the answer lives here.
 *
 * **On duty first, then everyone else.** The question asked at eleven at night
 * is "who is still here", and the question asked on payday is "how long did
 * each of them work" — the same list, ordered so the first one is answered
 * without reading.
 *
 * Read-only by design. Clocking somebody *else* in or out is a different thing
 * with an abuse surface of its own, and it is not offered here until it has the
 * permission flag and the audit row `FR-8.4` asks for.
 */
import { computed, ref, watch } from "vue";

import * as attendanceApi from "@/api/attendance";
import type { AttendanceRow } from "@/api/attendance";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, sinceWhen, t } from "@/i18n";

const props = defineProps<{ open: boolean; posProfile: string | null }>();
const emit = defineEmits<{ close: [] }>();

/** How far back to count. A day is the shift; a week is the pay question. */
const WINDOWS = [1, 7] as const;

const days = ref<number>(1);
const roster = ref<attendanceApi.Roster | null>(null);
const loading = ref(false);
const failure = ref<string | null>(null);

async function load(): Promise<void> {
  if (!props.posProfile) return;

  loading.value = true;
  failure.value = null;
  try {
    roster.value = await attendanceApi.getRoster(props.posProfile, days.value);
  } catch (cause) {
    roster.value = null;
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

watch([() => props.open, days], ([open]) => {
  if (open) void load();
});

/**
 * Hours and minutes, not a decimal.
 *
 * `7.5` is read as seven and a half by somebody who already knows the
 * convention and as seven-point-five by everybody else, and the difference is
 * an argument about pay. `7:30` cannot be misread.
 */
function spell(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return `${formatNumber(hours)}:${String(rest).padStart(2, "0")}`;
}

const people = computed<AttendanceRow[]>(() => roster.value?.people ?? []);
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('roster.title')"
    @close="emit('close')"
  >
    <div class="mb-4 flex items-center gap-2">
      <button
        v-for="window in WINDOWS"
        :key="window"
        type="button"
        class="min-h-tap rounded-rpos border px-4 text-sm font-medium transition duration-200 ease-rpos"
        :class="
          days === window
            ? 'border-primary bg-primary text-primary-contrast'
            : 'border-line-strong bg-background hover:border-primary'
        "
        @click="days = window"
      >
        {{ window === 1 ? t("roster.today") : t("roster.week") }}
      </button>
    </div>

    <p
      v-if="failure"
      role="alert"
      class="rounded-rpos bg-danger/10 px-3 py-2 text-sm text-danger"
    >
      {{ failure }}
    </p>

    <!-- A site with no HR app says so rather than showing an empty list, which
         reads as "nobody came to work today" (`D-135`). -->
    <p
      v-else-if="roster && !roster.available"
      class="rounded-rpos bg-accent-gold/10 px-3 py-2 text-sm text-accent-gold"
    >
      {{ t("roster.needsHr") }}
    </p>

    <p
      v-else-if="loading"
      class="py-8 text-center text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <p
      v-else-if="!people.length"
      class="py-8 text-center text-muted"
    >
      {{ t("roster.nobody") }}
    </p>

    <ul
      v-else
      class="divide-y divide-line"
    >
      <li
        v-for="row in people"
        :key="row.employee"
        class="flex items-baseline gap-3 py-3"
      >
        <!-- The dot is the answer to "who is still here", read without
             reading — and the name beside it is what a manager says out loud. -->
        <span
          class="h-[7px] w-[7px] shrink-0 rounded-full"
          :class="row.on_duty ? 'bg-secondary' : 'bg-line-strong'"
        />
        <span class="min-w-0 flex-1 truncate">{{ row.employee_name }}</span>
        <span
          v-if="row.on_duty && row.since"
          class="rpos-numeric shrink-0 text-xs text-muted"
        >{{ sinceWhen(row.since) }}</span>
        <span class="rpos-numeric shrink-0 text-base">{{ spell(row.minutes) }}</span>
      </li>
    </ul>
  </BaseDialog>
</template>
