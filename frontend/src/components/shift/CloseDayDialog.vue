<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { ShiftReport } from "@/api/shift";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import CashierTakings from "@/components/shift/CashierTakings.vue";
import { formatNumber, pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";

/**
 * End of day — the branch's report, and the decision to close on it (FR-8.2, 8.3).
 *
 * Shown before anything is committed, because closing the day is what the books
 * are written from and a cashier should see the figure they are signing off.
 *
 * **An order still open blocks it** where the branch says so (`D-105`), and the
 * way past that is a manager's right, not a tick box (`D-156`): closing across
 * an open bill strands it in a report that says the day is finished, and it
 * cannot be undone. And any drawer left open is swept up at its expected
 * figures — the cashier who went home is not coming back to count it.
 *
 * So an open bill reads three ways here, and each of them says something:
 * *settle them first* to a cashier, *carry over* where the branch allows it,
 * and the override to whoever may actually use it.
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const session = useSessionStore();
const shift = useShiftStore();

const report = ref<ShiftReport | null>(null);
const force = ref(false);

watch(
  () => props.open,
  async (isOpen) => {
    report.value = null;
    force.value = false;
    if (isOpen) report.value = await shift.daySummary();
  },
);

const stillOpen = computed(() => report.value?.orders.still_open ?? 0);

/** Still on the clock — every one of them goes home when this day closes. */
const onDuty = computed(() => report.value?.on_duty ?? 0);

/** Drawers nobody has counted, which closing the day closes at expected (`D-356`). */
const openTills = computed(() => report.value?.open_tills ?? []);

/**
 * Whether these open bills stand between the cashier and the end of the day.
 *
 * **Asked, not worked out.** The branch decides it (`D-105`) and the endpoint
 * enforces it; a screen that derived it again would be the second copy of the
 * rule that disagrees with the refusal. Absent — an older server — means any
 * open bill blocks, which is the stricter reading.
 */
const blocked = computed(() =>
  report.value ? (report.value.blocked_by_open_orders ?? Boolean(stillOpen.value)) : false,
);

/**
 * The branch is carrying more than it asked to be told about (`D-158`).
 *
 * Said, not enforced. The day closes on it — this is the pile getting noticed
 * while it is still small enough to clear.
 */
const carryingTooMany = computed(() => Boolean(report.value?.carrying_too_many));

/**
 * The override, and it is drawn only for someone who holds it.
 *
 * The server checks it again and is the authority — this decides whether to
 * draw a control, not whether the day may close (`04_performance_security.md`).
 */
const mayOverride = computed(() => session.can("can_close_day_with_open_orders"));

async function confirm(): Promise<void> {
  const done = await shift.closeDay(force.value);
  if (done) emit("close");
}

function money(value: number): string {
  return formatNumber(value, 2);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('shift.closeDayTitle')"
    @close="emit('close')"
  >
    <p
      v-if="!report"
      class="flex items-center gap-2 text-sm text-muted"
    >
      <AppIcon
        name="refresh"
        class="animate-spin"
        :size="18"
      />
      {{ t("common.loading") }}
    </p>

    <template v-else>
      <dl class="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded-rpos bg-background p-3 text-sm">
        <dt class="text-muted">
          {{ t("shift.ordersClosed") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ formatNumber(report.orders.closed) }}
        </dd>
        <dt class="text-muted">
          {{ t("shift.sales") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ money(report.sales) }}
        </dd>
        <dt class="text-muted">
          {{ t("totals.discount") }}
        </dt>
        <dd class="rpos-numeric text-end">
          {{ money(report.discounts) }}
        </dd>
        <dt class="text-muted">
          {{ t("shift.voids") }}
        </dt>
        <dd class="rpos-numeric text-end">
          {{ formatNumber(report.voids) }}
        </dd>
        <dt class="text-muted">
          <!-- `D-334` — not "expected in the till": a day has no float, so this is
               what the day's sales put in the drawers, and the drawer's own X
               report showed a different figure under the same words. -->
          {{ t("shift.dayTillNet") }}
        </dt>
        <dd class="rpos-numeric text-end font-semibold">
          {{ money(report.till_expected) }}
        </dd>
        <dt
          v-if="report.credit_total"
          class="text-muted"
        >
          {{ t("shift.creditTotal") }}
        </dt>
        <dd
          v-if="report.credit_total"
          class="rpos-numeric text-end"
        >
          {{ money(report.credit_total) }}
        </dd>
      </dl>

      <!-- FR-8.3 — how the day split, which is the first thing a manager looks at. -->
      <div
        v-if="report.by_order_type.length"
        class="mb-4 space-y-1"
      >
        <div
          v-for="row in report.by_order_type"
          :key="row.order_type"
          class="flex items-center justify-between gap-3 text-sm"
        >
          <span class="min-w-0 truncate">{{ pick(row.title_ar, row.order_type) }}</span>
          <span class="rpos-numeric shrink-0 text-muted">
            {{ formatNumber(row.count) }} · {{ money(row.sales) }}
          </span>
        </div>
      </div>

      <CashierTakings :rows="report.by_cashier" />

      <!-- The override, for whoever may actually use it. -->
      <label
        v-if="blocked && mayOverride"
        class="mb-4 flex items-start gap-3 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
      >
        <input
          v-model="force"
          type="checkbox"
          class="mt-0.5 h-5 w-5 shrink-0"
        >
        <span>{{ t("shift.stillOpen", { count: formatNumber(stillOpen) }) }}</span>
      </label>

      <!-- And the reason, for whoever may not. A disabled button with nothing
           beside it is the report a cashier cannot act on (`D-074`). -->
      <p
        v-else-if="blocked"
        role="status"
        class="mb-4 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
      >
        {{ t("shift.stillOpenBlocked", { count: formatNumber(stillOpen) }) }}
      </p>

      <!-- The pile is growing, and the day closes anyway (`D-158`). Said to the
           person ending the day, because they are the one who can act on it —
           the cashier who feels the slow list is not. -->
      <p
        v-else-if="carryingTooMany"
        role="status"
        class="mb-4 rounded-rpos bg-status-reserved/10 p-3 text-sm text-status-reserved"
      >
        {{ t("shift.carryingTooMany", { count: formatNumber(stillOpen) }) }}
      </p>

      <!-- The branch lets them run past midnight (`D-105`) — said out loud, so
           nobody thinks the till lost them. -->
      <p
        v-else-if="stillOpen"
        role="status"
        class="mb-4 rounded-rpos bg-status-cleaning/10 p-3 text-sm text-status-cleaning"
      >
        {{ t("shift.stillOpenCarries", { count: formatNumber(stillOpen) }) }}
      </p>

      <!-- **And the people, like the drawers** (`D-178`). Closing the day
           clocks out whoever is still on it, at this moment — said here rather
           than left to be found in a payroll report weeks later. Its own line,
           not an `v-else-if` in the chain above: it is true at the same time as
           an open bill, and the two are different facts. -->
      <div
        v-if="openTills.length"
        role="status"
        class="mb-4 rounded-rpos bg-danger/10 p-3 text-sm"
      >
        <p class="font-semibold text-danger">
          {{ t("shift.uncountedTills") }}
        </p>
        <ul class="mt-1 list-inside list-disc text-muted">
          <li
            v-for="till in openTills"
            :key="till.pos_profile + till.since"
          >
            {{ t("shift.uncountedTill", { terminal: till.pos_profile, user: till.user }) }}
          </li>
        </ul>
      </div>

      <p
        v-if="onDuty"
        role="status"
        class="mb-4 rounded-rpos bg-background p-3 text-sm text-muted"
      >
        {{ t("shift.clockingOut", { count: formatNumber(onDuty) }) }}
      </p>

      <p
        v-if="shift.error"
        role="alert"
        class="mb-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ shift.error }}
      </p>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="emit('close')"
        >
          {{ t("action.undo") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="shift.busy || (blocked && !force)"
          @click="confirm"
        >
          {{ t("shift.closeDay") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
