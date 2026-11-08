<script setup lang="ts">
import { ref, watch } from "vue";

import { agentFileUrl, installAgent, type AgentInstall } from "@/api/printing";
import BaseDialog from "@/components/BaseDialog.vue";
import { t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * The print agent, installed from this till in one step (`D-424`, `docs/11` §4).
 *
 * The server sets the terminal to print direct, makes or takes its agent, and
 * hands back the agent's program named with this page's address and a pairing
 * code: run it, and it pairs itself. Four states, each one said on screen —
 * asking, asking the manager about another computer, done, refused (`D-074`).
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

const session = useSessionStore();

type State = "asking" | "move" | "done" | "failed";
const state = ref<State>("asking");
const otherComputer = ref("");
const error = ref("");

async function ask(move: boolean): Promise<void> {
  state.value = "asking";
  let answer: AgentInstall;
  try {
    answer = await installAgent(session.profile?.name ?? "", move);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause);
    state.value = "failed";
    return;
  }

  if (answer.needs_move) {
    otherComputer.value = answer.needs_move;
    state.value = "move";
    return;
  }

  // The browser's own download: twenty-odd megabytes are not held in the page.
  const link = document.createElement("a");
  link.href = agentFileUrl(answer.ticket ?? "");
  link.download = answer.filename ?? "";
  link.click();
  state.value = "done";
}

watch(
  () => props.open,
  (open) => {
    if (open) void ask(false);
  },
  { immediate: true },
);
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('agent.installTitle')"
    @close="emit('close')"
  >
    <p
      v-if="state === 'asking'"
      class="text-sm text-muted"
    >
      {{ t("agent.preparing") }}
    </p>

    <template v-else-if="state === 'move'">
      <p class="mb-4 text-sm">
        {{ t("agent.moveBody", { computer: otherComputer }) }}
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
          class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white"
          @click="ask(true)"
        >
          {{ t("agent.moveHere") }}
        </button>
      </div>
    </template>

    <template v-else-if="state === 'done'">
      <ol class="mb-4 list-decimal space-y-1 ps-5 text-sm">
        <li>{{ t("agent.stepRun") }}</li>
        <li>{{ t("agent.stepWarning") }}</li>
        <li>{{ t("agent.stepClock") }}</li>
      </ol>
      <button
        type="button"
        class="min-h-tap w-full rounded-rpos bg-primary font-medium text-primary-contrast"
        @click="emit('close')"
      >
        {{ t("agent.understood") }}
      </button>
    </template>

    <p
      v-else
      class="text-sm text-danger"
    >
      {{ error }}
    </p>
  </BaseDialog>
</template>
