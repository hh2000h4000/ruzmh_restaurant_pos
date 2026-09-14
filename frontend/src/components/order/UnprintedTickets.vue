<script setup lang="ts">
import type { UnprintedTicket } from "@/api/order";
import { pick, t } from "@/i18n";

/**
 * Kitchen tickets whose paper never came (`D-211`).
 *
 * A printer that was off used to fail in silence: the ticket said `failed` on a
 * desk form nobody opens during service, and the cook simply got nothing — the
 * first anyone heard was a customer asking where the food was. So the order
 * says it, one line per station, with the way out beside it.
 *
 * The button is drawn only for a cashier who may reprint; the server checks
 * `can_reprint_receipt` again (`CLAUDE.md` §5.4). Anybody else is told who can,
 * rather than shown a button that refuses.
 */
defineProps<{
  tickets: UnprintedTicket[];
  mayReprint: boolean;
  busy: boolean;
}>();

defineEmits<{ reprint: [kotName: string] }>();
</script>

<template>
  <div
    v-for="ticket in tickets"
    :key="ticket.kot_name"
    role="alert"
    class="flex flex-wrap items-center justify-between gap-2 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
  >
    <span>{{ t("order.ticketNotPrinted", { station: pick(ticket.station_ar, ticket.station) }) }}</span>

    <button
      v-if="mayReprint"
      type="button"
      class="rounded-rpos border border-danger/40 px-3 py-1.5 font-medium transition duration-200 ease-rpos hover:bg-danger/10 disabled:opacity-50"
      :disabled="busy"
      @click="$emit('reprint', ticket.kot_name)"
    >
      {{ t("order.reprintTicket") }}
    </button>
    <span
      v-else
      class="text-xs"
    >
      {{ t("order.askForReprint") }}
    </span>
  </div>
</template>
