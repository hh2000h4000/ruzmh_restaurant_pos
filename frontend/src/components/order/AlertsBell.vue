<script setup lang="ts">
import { computed, ref } from "vue";

import { markKitchenTold, reprintKot, type PrintAlert } from "@/api/kitchen";
import AppIcon from "@/components/AppIcon.vue";
import { useDismiss } from "@/composables/useDismiss";
import { dateOnly, formatNumber, pick, t, timeOnly, type MessageKey } from "@/i18n";
import { useAlertsStore } from "@/stores/alerts";
import { useConnectionStore } from "@/stores/connection";

/**
 * The bell (`D-299`): a small button in the corner of the action row that opens
 * the alerts over the screen, the way modern apps do.
 *
 * It replaced a tab in the bottom bar and a pane that took the whole content
 * area (`D-298`), which the user found heavy for something a cashier glances
 * at. Built to the user's own design: quiet until there is something unread,
 * then a small red count; the panel opens under the bell over a very light
 * shade, and a tap outside puts it away.
 *
 * **Each alert reads in two seconds**: what happened, which bill, when — and
 * the one thing to do about it, if anything is left to do.
 *
 * Two places this departs from the design, both on purpose:
 * - **`click`, not `pointerdown`.** `main.css` explains it: a press acted on
 *   before the browser knows the finger is scrolling puts the wrong thing on
 *   the wrong bill. The list here scrolls.
 * - **✕ only on an alert that needs nothing.** Striking off a ticket that
 *   never reached the kitchen would hide the one alert this bell exists for.
 */
defineProps<{ mayReprint: boolean }>();

const alerts = useAlertsStore();
const connection = useConnectionStore();

const open = ref(false);
// Unread first, at the user's request: what is new is what the bell is opened for.
const onlyUnread = ref(true);
const busy = ref(false);
const failure = ref<string | null>(null);

const anchor = useDismiss(open);

const shown = computed(() => (onlyUnread.value ? alerts.rows.filter(alerts.isUnread) : alerts.rows));
const first = computed(() => alerts.start === 0);

function toggle(): void {
  open.value = !open.value;
  if (open.value) void alerts.refresh();
}

async function act(row: PrintAlert, run: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  try {
    await run();
    alerts.markRead(row.kot_name);
    failure.value = null;
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
    await (first.value ? alerts.refresh() : alerts.turn(alerts.start));
  }
}

function localDay(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** "Order 4 · 11:39" — the bill as the cashier calls it, and when it failed. */
function source(row: PrintAlert): string {
  const bill = row.call_name || t("alerts.order", { number: formatNumber(row.daily_number ?? 0) });
  const where = row.table_number ? ` · ${t("card.table", { number: row.table_number })}` : "";
  const day = row.failed_at.slice(0, 10) === localDay() ? "" : `${dateOnly(row.failed_at)} `;
  const ended = row.state === "failed" ? "" : ` · ${t(`alerts.state.${row.state}` as MessageKey)}`;
  return `${bill}${where} · ${day}${timeOnly(row.failed_at)}${ended}`;
}
</script>

<template>
  <div
    ref="anchor"
    class="relative shrink-0"
  >
    <button
      type="button"
      class="relative grid h-[3.375rem] w-[3.375rem] place-items-center rounded-rpos border transition duration-150 ease-rpos active:scale-[0.96]"
      :class="
        open
          ? 'border-primary bg-primary text-primary-contrast'
          : 'border-line-strong bg-surface text-content hover:border-primary/45'
      "
      :aria-label="t('alerts.title')"
      :aria-expanded="open"
      @click="toggle"
    >
      <AppIcon
        name="bell"
        :size="22"
      />
      <span
        v-if="alerts.unread"
        class="rpos-numeric absolute -end-1.5 -top-1.5 grid h-[1.375rem] min-w-[1.375rem] place-items-center rounded-full border-2 border-background bg-danger px-1.5 text-[11.5px] font-medium text-white"
      >{{ formatNumber(alerts.unread) }}</span>
    </button>

    <!-- The shade: very light, and only to take the tap that closes the panel. -->
    <div
      v-if="open"
      class="fixed inset-0 z-30 bg-content/[0.06]"
      @click="open = false"
    />

    <section
      v-if="open"
      class="rpos-pop absolute end-0 top-[4.125rem] z-40 grid max-h-[calc(100vh-120px)] w-[min(420px,calc(100vw-36px))] grid-rows-[auto_auto_minmax(0,1fr)_auto] overflow-hidden rounded-[20px] border border-line bg-surface shadow-lift"
    >
      <header class="flex items-center justify-between gap-3 whitespace-nowrap px-[22px] pb-3.5 pt-5">
        <h2 class="flex items-baseline gap-2.5">
          <span class="text-lg font-semibold">{{ t("alerts.title") }}</span>
          <span
            v-if="alerts.unread"
            class="text-[13px] text-muted"
          >{{ t("alerts.unread", { count: formatNumber(alerts.unread) }) }}</span>
        </h2>
        <button
          v-if="alerts.unread"
          type="button"
          class="min-h-9 rounded-[10px] px-2.5 text-[13px] text-primary transition-colors duration-150 hover:bg-primary/10"
          @click="alerts.markAllRead()"
        >
          {{ t("alerts.markAllRead") }}
        </button>
      </header>

      <div class="flex gap-1.5 px-[22px] pb-3.5">
        <button
          v-for="tab in [true, false]"
          :key="String(tab)"
          type="button"
          class="h-10 rounded-[11px] px-4 text-[13.5px] font-medium transition-colors duration-150"
          :class="onlyUnread === tab ? 'bg-content text-surface' : 'bg-background text-muted'"
          @click="onlyUnread = tab"
        >
          {{ tab ? t("alerts.tabUnread") : t("alerts.tabAll") }}
        </button>
      </div>

      <div class="min-h-0 overflow-y-auto overflow-x-hidden border-t border-line">
        <p
          v-if="failure || alerts.failure"
          role="alert"
          class="m-4 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
        >
          {{ failure || alerts.failure }}
        </p>
        <p
          v-if="!connection.isOnline"
          class="m-4 rounded-rpos bg-background p-3 text-[13px] text-muted"
        >
          {{ t("alerts.offline") }}
        </p>

        <div
          v-if="!shown.length"
          class="px-[22px] py-14 text-center"
        >
          <p class="text-[14.5px] text-muted">
            {{ alerts.loading ? t("alerts.loading") : t("alerts.none") }}
          </p>
          <p
            v-if="!alerts.loading"
            class="mt-1 text-[13px] text-subtle"
          >
            {{ t("alerts.noneHint") }}
          </p>
        </div>

        <ul v-else>
          <li
            v-for="row in shown"
            :key="row.kot_name"
            class="grid grid-cols-[36px_minmax(0,1fr)_36px] gap-3.5 border-b border-line/60 px-[22px] py-4"
            :class="alerts.isUnread(row) ? 'bg-background/40' : 'bg-surface'"
          >
            <span
              class="grid h-9 w-9 place-items-center rounded-[11px] text-[15px] font-semibold"
              :class="
                row.state === 'printed' || row.state === 'told'
                  ? 'bg-primary/10 text-primary'
                  : 'bg-accent-gold/15 text-accent-gold'
              "
              aria-hidden="true"
            >{{ row.state === "printed" || row.state === "told" ? "✓" : "!" }}</span>

            <div class="grid min-w-0 gap-1">
              <p
                class="text-[14.5px] text-content [text-wrap:pretty]"
                :class="alerts.isUnread(row) ? 'font-semibold' : 'font-normal'"
              >
                {{ t("alerts.ticket", { station: pick(row.station_ar, row.station) }) }}
              </p>
              <p class="rpos-numeric text-[12.5px] text-muted">
                {{ source(row) }}
              </p>
              <div
                v-if="row.state === 'failed'"
                class="mt-2 flex flex-wrap gap-2"
              >
                <button
                  type="button"
                  class="h-10 rounded-[11px] bg-primary px-4 text-[13px] font-medium text-primary-contrast transition-colors duration-150 hover:bg-primary/90 disabled:opacity-50"
                  :disabled="busy"
                  @click="act(row, () => markKitchenTold(row.kot_name))"
                >
                  {{ t("alerts.told") }}
                </button>
                <button
                  v-if="mayReprint"
                  type="button"
                  class="h-10 rounded-[11px] border border-line-strong px-4 text-[13px] font-medium transition-colors duration-150 hover:border-primary disabled:opacity-50"
                  :disabled="busy"
                  @click="act(row, () => reprintKot(row.kot_name))"
                >
                  {{ t("order.reprintTicket") }}
                </button>
              </div>
            </div>

            <div class="flex flex-col items-center gap-2.5">
              <span
                v-if="alerts.isUnread(row)"
                class="mt-1.5 h-2 w-2 rounded-full bg-primary"
                :aria-label="t('alerts.tabUnread')"
              />
              <button
                v-if="row.state !== 'failed'"
                type="button"
                class="grid h-9 w-9 place-items-center rounded-[10px] text-[13px] text-subtle transition-colors duration-150 hover:bg-background hover:text-content"
                :aria-label="t('alerts.hide')"
                @click="alerts.hide(row.kot_name)"
              >
                ✕
              </button>
            </div>
          </li>
        </ul>
      </div>

      <footer class="grid grid-cols-[auto_minmax(0,1fr)_auto] border-t border-line">
        <button
          v-if="!first"
          type="button"
          class="h-[52px] px-4 text-[13.5px] text-muted transition-colors duration-150 hover:bg-background disabled:opacity-40"
          :disabled="alerts.loading"
          @click="alerts.turn(Math.max(0, alerts.start - alerts.page))"
        >
          {{ t("alerts.newer") }}
        </button>
        <span v-else />
        <button
          type="button"
          class="flex h-[52px] items-center justify-center gap-2 text-[13.5px] text-muted transition-colors duration-150 hover:bg-background disabled:opacity-40"
          :disabled="alerts.loading"
          @click="first ? alerts.refresh() : alerts.turn(alerts.start)"
        >
          <AppIcon
            name="refresh"
            :size="16"
          />
          {{ t("alerts.refresh") }}
        </button>
        <button
          v-if="alerts.more"
          type="button"
          class="h-[52px] px-4 text-[13.5px] text-muted transition-colors duration-150 hover:bg-background disabled:opacity-40"
          :disabled="alerts.loading"
          @click="alerts.turn(alerts.start + alerts.page)"
        >
          {{ t("alerts.older") }}
        </button>
        <span v-else />
      </footer>
    </section>
  </div>
</template>

<style scoped>
/* 160ms from just above, as the design asks — opacity and transform only. */
/* Grown from the bell's corner: the left one in Arabic, the right in English. */
.rpos-pop {
  transform-origin: top left;
  animation: rpos-pop 160ms ease-out;
}

[dir="ltr"] .rpos-pop {
  transform-origin: top right;
}

@keyframes rpos-pop {
  from {
    opacity: 0;
    transform: translateY(-6px) scale(0.98);
  }
}
</style>
