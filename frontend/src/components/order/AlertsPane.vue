<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import {
  getPrintAlerts,
  markKitchenTold,
  reprintKot,
  type PrintAlert,
  type PrintAlertState,
} from "@/api/kitchen";
import AppIcon from "@/components/AppIcon.vue";
import { dateOnly, formatNumber, pick, t, timeOnly, type MessageKey } from "@/i18n";
import { useAlertsStore } from "@/stores/alerts";
import { useConnectionStore } from "@/stores/connection";
import { useSessionStore } from "@/stores/session";

/**
 * The bell (`D-298`): every kitchen ticket in the branch that did not print.
 *
 * It replaces a banner per ticket on the bill, which stood over the items for
 * as long as a printer stayed off — two lines for one station when it had two
 * tickets. Simphony puts the same alert behind one button; this is that button.
 *
 * **Twenty at a time**, the user's rule: the newest page first, and the older
 * twenty only when asked for. A page replaces the one before it rather than
 * growing the list — a printer off all evening is a hundred rows nobody reads.
 *
 * Each ticket still waiting can be printed again, or answered for by hand:
 * "I told the kitchen". That is recorded with the cashier's name, never hidden.
 */
defineProps<{ mayReprint: boolean }>();

const session = useSessionStore();
const connection = useConnectionStore();
const badge = useAlertsStore();

const start = ref(0);
const rows = ref<PrintAlert[]>([]);
const more = ref(false);
const loading = ref(false);
const busy = ref(false);
const failure = ref<string | null>(null);

const page = ref(20);
const first = computed(() => start.value === 0);

onMounted(load);
watch(start, load);
watch(
  () => connection.isOnline,
  (online) => {
    if (online) void load();
  },
);

async function load(): Promise<void> {
  if (!connection.isOnline) {
    failure.value = t("alerts.offline");
    return;
  }

  loading.value = true;
  try {
    const answer = await getPrintAlerts(session.profile!.name, start.value);
    rows.value = answer.alerts;
    more.value = answer.more;
    page.value = answer.page;
    badge.open = answer.open;
    failure.value = null;
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    loading.value = false;
  }
}

async function act(run: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  try {
    await run();
    failure.value = null;
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
    await load();
  }
}

/** The bill as the cashier calls it: its name, else its number, and the table. */
function which(row: PrintAlert): string {
  const bill = row.call_name || t("alerts.order", { number: formatNumber(row.daily_number ?? 0) });
  return row.table_number ? `${bill} · ${t("card.table", { number: row.table_number })}` : bill;
}

const TONE: Record<PrintAlertState, string> = {
  failed: "bg-danger/10 text-danger",
  printing: "bg-status-cleaning/10 text-status-cleaning",
  printed: "bg-primary/10 text-primary",
  told: "bg-background text-muted",
};
</script>

<template>
  <section
    class="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)_auto] gap-4 rounded-rpos bg-surface p-5 shadow-card"
  >
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="flex items-center gap-2 text-xl font-bold">
        <AppIcon
          name="bell"
          :size="24"
        />
        {{ t("alerts.title") }}
      </h2>
      <button
        type="button"
        class="flex min-h-tap items-center gap-2 rounded-rpos border border-line-strong px-4 text-sm font-medium transition duration-200 ease-rpos hover:border-primary disabled:opacity-50"
        :disabled="loading"
        @click="load"
      >
        <AppIcon
          name="refresh"
          :size="18"
        />
        {{ t("alerts.refresh") }}
      </button>
    </div>

    <div class="min-h-0 overflow-y-auto">
      <p
        v-if="failure"
        role="alert"
        class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
      >
        {{ failure }}
      </p>

      <p
        v-if="loading && !rows.length"
        class="p-6 text-center text-sm text-muted"
      >
        {{ t("alerts.loading") }}
      </p>
      <p
        v-else-if="!rows.length"
        class="p-6 text-center text-sm text-muted"
      >
        {{ t("alerts.none") }}
      </p>
      <ul
        v-else
        class="flex flex-col divide-y divide-line"
      >
        <li
          v-for="row in rows"
          :key="row.kot_name"
          class="flex flex-wrap items-center justify-between gap-3 py-3"
        >
          <div class="min-w-0">
            <p class="font-medium">
              {{ t("alerts.ticket", { station: pick(row.station_ar, row.station) }) }}
            </p>
            <p class="mt-0.5 text-xs text-muted">
              {{ which(row) }} · {{ dateOnly(row.failed_at) }} {{ timeOnly(row.failed_at) }}
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-2">
            <span
              class="rounded-full px-3 py-1 text-xs font-medium"
              :class="TONE[row.state]"
            >{{ t(`alerts.state.${row.state}` as MessageKey) }}</span>

            <template v-if="row.state === 'failed'">
              <button
                v-if="mayReprint"
                type="button"
                class="min-h-tap rounded-rpos border border-danger/40 px-3 text-sm font-medium text-danger transition duration-200 ease-rpos hover:bg-danger/10 disabled:opacity-50"
                :disabled="busy"
                @click="act(() => reprintKot(row.kot_name))"
              >
                {{ t("order.reprintTicket") }}
              </button>
              <button
                type="button"
                class="min-h-tap rounded-rpos border border-line-strong px-3 text-sm font-medium transition duration-200 ease-rpos hover:border-primary disabled:opacity-50"
                :disabled="busy"
                @click="act(() => markKitchenTold(row.kot_name))"
              >
                {{ t("alerts.told") }}
              </button>
            </template>
          </div>
        </li>
      </ul>
    </div>

    <div
      v-if="!first || more"
      class="flex items-center justify-between gap-3"
    >
      <button
        type="button"
        class="min-h-tap rounded-rpos border border-line-strong px-4 text-sm font-medium transition duration-200 ease-rpos hover:border-primary disabled:opacity-40"
        :disabled="first || loading"
        @click="start = Math.max(0, start - page)"
      >
        {{ t("alerts.newer") }}
      </button>
      <button
        type="button"
        class="min-h-tap rounded-rpos border border-line-strong px-4 text-sm font-medium transition duration-200 ease-rpos hover:border-primary disabled:opacity-40"
        :disabled="!more || loading"
        @click="start += page"
      >
        {{ t("alerts.older") }}
      </button>
    </div>
  </section>
</template>
