<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { OrderDetail } from "@/api/order";
import { mergeTables } from "@/api/order";
import { getFloorPlan, type FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, t, tn } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * One party across more than one table (`BR-063`, `FR-5.4`).
 *
 * **A restaurant says "merge" for two different things, and the app has both.**
 * This joins *tables* — a group of ten takes 5 and 6, orders together, and both
 * seats stay drawn taken until the one bill is paid. `JoinBillDialog` merges
 * *bills*, which is what to reach for when each table already ordered.
 *
 * So a table that already carries a bill is **listed and disabled**, with the
 * other dialog named on it, rather than hidden: a cashier looking for table 6
 * and not finding it learns nothing, and the server refuses it anyway.
 *
 * Free tables only, from the bill's own hall — a party spread across two halls
 * is not a party.
 */
const props = defineProps<{ open: boolean; order: OrderDetail | null }>();
const emit = defineEmits<{ joined: [tables: string[]]; close: [] }>();

const session = useSessionStore();

const tables = ref<FloorTable[]>([]);
const chosen = ref<string[]>([]);
const loading = ref(false);
const busy = ref(false);
const error = ref<string | null>(null);

/** The tables this bill already holds — its own seat, and any joined before. */
const held = computed(() => new Set(props.order?.tables ?? []));

const offered = computed(() => tables.value.filter((table) => !held.value.has(table.name)));

/** A table with a bill on it is the other dialog's job (`BR-067`). */
const takenBy = (table: FloorTable) => (table.orders ?? []).length;

const free = (table: FloorTable) =>
  !takenBy(table) && (table.status === "available" || table.status === "reserved");

watch(
  () => props.open,
  async (isOpen) => {
    chosen.value = [];
    error.value = null;
    if (!isOpen) return;

    loading.value = true;
    try {
      const section = props.order?.section ?? session.data?.restaurant_section?.name;
      tables.value = section ? (await getFloorPlan(section)).tables : [];
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
    } finally {
      loading.value = false;
    }
  },
);

function toggle(table: FloorTable): void {
  if (!free(table)) return;

  chosen.value = chosen.value.includes(table.name)
    ? chosen.value.filter((name) => name !== table.name)
    : [...chosen.value, table.name];
}

async function confirm(): Promise<void> {
  if (!props.order || !chosen.value.length || busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    const done = await mergeTables({
      order_name: props.order.order_name,
      tables: chosen.value,
    });
    emit("joined", done.joined);
  } catch (cause) {
    // The server is the authority on every one of these rules, so its sentence
    // is the one shown rather than a guess made here (`CLAUDE.md` §5.4).
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('tables.joinTitle')"
    @close="emit('close')"
  >
    <p class="mb-4 text-xs text-subtle">
      {{ t("tables.joinBody") }}
    </p>

    <p
      v-if="loading"
      class="text-xs text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <!-- `D-074` — every path ends in something readable. A hall with nothing
         free says so rather than drawing an empty box. -->
    <p
      v-else-if="!offered.length"
      class="rounded-rpos bg-background p-3 text-xs text-subtle"
    >
      {{ t("tables.joinEmpty") }}
    </p>

    <div
      v-else
      class="mb-4 grid max-h-[46vh] grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-3"
    >
      <button
        v-for="table in offered"
        :key="table.name"
        type="button"
        class="flex min-h-tap flex-col items-center justify-center gap-1 rounded-rpos border p-3 transition-colors duration-100 ease-rpos disabled:opacity-45"
        :class="
          chosen.includes(table.name)
            ? 'border-primary bg-primary text-primary-contrast'
            : 'border-line bg-background text-content'
        "
        :disabled="!free(table)"
        :aria-pressed="chosen.includes(table.name)"
        @click="toggle(table)"
      >
        <span class="rpos-numeric text-[17px] font-medium">{{ table.table_number }}</span>
        <span class="text-label">
          {{ takenBy(table) ? t("tables.joinHasBill") : tn("count.seats", table.capacity ?? 0) }}
        </span>
      </button>
    </div>

    <p
      v-if="error"
      role="alert"
      class="mb-3 rounded-rpos bg-danger/10 p-3 text-xs text-danger"
    >
      {{ error }}
    </p>

    <div class="flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.cancel") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
        :disabled="busy || !chosen.length"
        @click="confirm"
      >
        {{ t("tables.joinConfirm", { count: formatNumber(chosen.length) }) }}
      </button>
    </div>
  </BaseDialog>
</template>
