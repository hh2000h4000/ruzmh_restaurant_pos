<script setup lang="ts">
import { ref, watch } from "vue";

import { setTableStatus, type FloorTable } from "@/api/table";
import BaseDialog from "@/components/BaseDialog.vue";
import { t } from "@/i18n";

/**
 * "Table {n} is wiped down" — the one answer a `cleaning` table waits for.
 *
 * Paying the last bill sends a table to `cleaning` rather than straight to free
 * (`utils/payment.release_tables_of`), because a paid table is not a table
 * anybody can sit at yet. Only a person knows when it is, and until this dialog
 * existed nobody could say so: the status was set by the server and cleared by
 * nothing, so a table that took one bill was out of service for good.
 *
 * **One dialog for both screens** (`CLAUDE.md` §5.5). The floor is drawn in two
 * places — the Tables screen and the order screen's floor pane — and the
 * question a cashier is answering is the same in both, so it is asked once here
 * rather than written twice.
 */
const props = defineProps<{ table: FloorTable | null }>();
const emit = defineEmits<{ done: []; close: [] }>();

const busy = ref(false);
const error = ref<string | null>(null);

watch(
  () => props.table,
  () => {
    error.value = null;
  },
);

async function confirm(): Promise<void> {
  if (!props.table || busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    await setTableStatus(props.table.name, "available");
    emit("done");
  } catch (cause) {
    // The server owns the rule — a table still carrying a bill is refused
    // there — so its sentence is the one shown (`CLAUDE.md` §5.4).
    error.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="Boolean(table)"
    :title="t('tables.readyTitle', { number: table?.table_number ?? '' })"
    @close="emit('close')"
  >
    <p class="mb-4 text-xs text-subtle">
      {{ t("tables.readyBody") }}
    </p>

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
        :disabled="busy"
        @click="confirm"
      >
        {{ t("tables.readyConfirm") }}
      </button>
    </div>
  </BaseDialog>
</template>
