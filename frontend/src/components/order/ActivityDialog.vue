<script setup lang="ts">
import { computed, ref, watch } from "vue";

import * as api from "@/api/activity";
import type { ActivityEntry } from "@/api/activity";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import { t, timeOnly } from "@/i18n";
import type { MessageKey } from "@/i18n";

/**
 * What happened to this bill, and who did it (`D-106`).
 *
 * **Every line is a sentence, in the language on the screen.** The reference
 * this was built against leaks its own internals at the cashier — untranslated
 * Polish and a mojibake question mark in the middle of a receipt total — and
 * repeats "recalculated bill" three times for one payment. Neither is a
 * detail: a log a cashier cannot read is a log nobody opens, and noise is what
 * makes the one line that matters impossible to find.
 *
 * So the wording is composed here from `action` and `subject`, not stored as a
 * finished sentence on the server: a bill opened by an Arabic-speaking cashier
 * and read by an English-speaking manager has to read correctly for both.
 */
const props = defineProps<{ orderName: string | null; number: number | null }>();
const open = defineModel<boolean>({ required: true });

const entries = ref<ActivityEntry[]>([]);
const loading = ref(false);
const failed = ref(false);

watch(open, async (showing) => {
  if (!showing || !props.orderName) return;

  loading.value = true;
  failed.value = false;
  try {
    entries.value = await api.timeline(props.orderName);
  } catch {
    failed.value = true;
  } finally {
    loading.value = false;
  }
});

/** `log.<action>` for anything we know; the raw action if the server adds one. */
function describe(entry: ActivityEntry): string {
  const key = `log.${entry.action}` as MessageKey;
  const line = t(key, { subject: entry.subject ?? "" });

  // An unknown action must not print `log.something` at a cashier — the exact
  // failure the reference screen shows with its untranslated rows.
  return line === key ? entry.action : line.replace(/\s+—\s*$/, "");
}

const count = computed(() => entries.value.length);
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('log.title', { number: number ?? '' })"
    :dismissible="true"
    @close="open = false"
  >
    <p
      v-if="loading"
      class="py-6 text-center text-muted"
    >
      {{ t("common.loading") }}
    </p>

    <p
      v-else-if="failed"
      class="py-6 text-center text-danger"
      role="alert"
    >
      {{ t("log.failed") }}
    </p>

    <p
      v-else-if="!count"
      class="py-6 text-center text-muted"
    >
      {{ t("log.empty") }}
    </p>

    <div
      v-else
      class="max-h-[60vh] overflow-y-auto"
    >
      <ol class="space-y-1">
        <li
          v-for="entry in entries"
          :key="entry.name"
          class="flex items-start gap-3 rounded-rpos px-2 py-2 odd:bg-surface"
        >
          <span class="rpos-numeric shrink-0 pt-0.5 text-xs text-muted">
            {{ timeOnly(entry.at) }}
          </span>

          <span class="min-w-0 flex-1">
            <span class="block text-sm font-medium text-content">
              {{ describe(entry) }}
            </span>
            <span class="block text-xs text-muted">{{ entry.user_name }}</span>
          </span>

          <!-- Marked, not filtered: a void belongs in the story *and* in the
               compliance log, and the reader should see which is which. -->
          <AppIcon
            v-if="entry.audit_log"
            name="document"
            :size="14"
            class="mt-1 shrink-0 text-primary"
            :aria-label="t('log.sensitive')"
          />
        </li>
      </ol>

      <p class="mt-3 text-center text-xs text-muted">
        {{ t("log.count", { count }) }}
      </p>
    </div>
  </BaseDialog>
</template>
