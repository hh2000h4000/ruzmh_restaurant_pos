<script setup lang="ts">
import { ref, watch } from "vue";

import BaseDialog from "@/components/BaseDialog.vue";
import NoteEditor from "@/components/order/NoteEditor.vue";
import { t } from "@/i18n";

/**
 * *Why?* — asked once, wherever the till has to be told (`BR-013`).
 *
 * **One question, one screen** (`CLAUDE.md` §5.5). Taking a line off a printed
 * ticket and cancelling the whole bill are two acts and one question: the
 * cashier types a reason, and nothing happens until they do. The order screen
 * carried two copies of this box, identical but for four strings — and the
 * copies had already drifted: the cancellation box showed *"Reason for
 * voiding"* as its ghost text, which is the other dialog's **title**.
 *
 * What differs is what to call it and what the confirming button says, so those
 * are props. The rule itself — a reason is mandatory, and the button stays dead
 * without one — is written here once.
 */
const props = defineProps<{
  open: boolean;
  title: string;
  /** The line under the title: what is about to be reversed. */
  explain: string;
  placeholder: string;
  /** What the destructive button says, in the words of the act. */
  confirm: string;
  /** Which ready-made reasons to offer (`D-239`). */
  scope: "void_reason" | "cancel_reason";
  busy?: boolean;
}>();

const emit = defineEmits<{ confirm: [reason: string]; close: [] }>();

const reason = ref("");

// A reason belongs to the act it was given for. Reopening the box for the next
// line must not offer the last one's words, half-typed, as an answer.
watch(
  () => props.open,
  () => {
    reason.value = "";
  },
);

function submit(): void {
  const given = reason.value.trim();
  if (!given || props.busy) return;

  emit("confirm", given);
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="title"
    @close="emit('close')"
  >
    <p class="mb-3 text-sm text-muted">
      {{ explain }}
    </p>

    <!-- Tap the usual answer, or write the one that is not there (`D-239`). -->
    <NoteEditor
      v-model="reason"
      class="mb-4"
      :scope="scope"
      :placeholder="placeholder"
      single
    />

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
        class="min-h-tap flex-1 rounded-rpos bg-danger font-medium text-white disabled:opacity-50"
        :disabled="busy || !reason.trim()"
        @click="submit"
      >
        {{ confirm }}
      </button>
    </div>
  </BaseDialog>
</template>
