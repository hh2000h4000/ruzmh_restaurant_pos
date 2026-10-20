<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { moveDrawerCash } from "@/api/shift";
import { validateManagerOverride } from "@/api/payment";
import BaseDialog from "@/components/BaseDialog.vue";
import ManagerPinDialog from "@/components/ManagerPinDialog.vue";
import AmountKeypad from "@/components/shift/AmountKeypad.vue";
import ReasonDialog from "@/components/order/ReasonDialog.vue";
import { formatNumber, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Notes in or out of the open drawer, for something that is not a sale (`D-245`).
 *
 * The cashier sends somebody for a bag of ice, or fetches change from the safe.
 * Until this existed the notes moved and nothing recorded it, so the count at
 * closing came up short by exactly that much and the shortage landed on whoever
 * was holding the drawer.
 *
 * **One dialog for both directions.** In and out ask the same three things —
 * which way, how much, what for — so the direction is a choice inside it rather
 * than a second screen (`CLAUDE.md` §5.5).
 *
 * **The reason is required and tappable.** A drawer short by a figure nobody can
 * explain is the whole defect; a free-text box in a rush gets "x". The chips come
 * from the quick notes a manager already keeps (`D-239`).
 */
const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: []; done: [] }>();

const session = useSessionStore();

const direction = ref<"in" | "out">("out");
const amount = ref("0");
const reason = ref("");
const busy = ref(false);
const error = ref<string | null>(null);
const askingReason = ref(false);
const askingManager = ref(false);
const overrideToken = ref<string | null>(null);

const allowed = computed(() => session.can("can_move_drawer_cash"));
const value = computed(() => Number(amount.value) || 0);

/** What the manager is being asked to approve, in one line. */
const explain = computed(
  () =>
    `${t(direction.value === "out" ? "drawerCash.out" : "drawerCash.in")} ${formatNumber(value.value, 2)}`,
);

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    direction.value = "out";
    amount.value = "0";
    reason.value = "";
    error.value = null;
    overrideToken.value = null;
  },
);

function approveWith(pin: string, why: string): Promise<string> {
  return validateManagerOverride({
    action_type: "can_move_drawer_cash",
    pin,
    reason: why,
    branch: session.branch ?? "",
    pos_profile: session.profile?.name ?? "",
  }).then((approval) => approval.override_token);
}

function onApproved(token: string): void {
  overrideToken.value = token;
  askingManager.value = false;
  void send();
}

/** The reason comes first: a manager should see what they are approving. */
function onReason(chosen: string): void {
  reason.value = chosen;
  askingReason.value = false;
  if (!allowed.value && !overrideToken.value) {
    askingManager.value = true;
    return;
  }
  void send();
}

function confirm(): void {
  if (value.value <= 0 || busy.value) return;
  askingReason.value = true;
}

async function send(): Promise<void> {
  if (busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    await moveDrawerCash({
      pos_profile: session.profile?.name ?? "",
      direction: direction.value,
      amount: value.value,
      reason: reason.value,
      override_token: overrideToken.value,
    });
    emit("done");
  } catch (cause) {
    // The server owns every rule here — the open drawer, the branch, the
    // permission — so its sentence is the one shown (`CLAUDE.md` §5.4).
    error.value = cause instanceof Error ? cause.message : String(cause);
    overrideToken.value = null;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="t('drawerCash.title')"
    pad
    @close="emit('close')"
  >
    <p class="mb-3 text-center text-xs text-subtle">
      {{ t("drawerCash.body") }}
    </p>

    <div class="mb-4 grid grid-cols-2 gap-2">
      <button
        v-for="way in (['out', 'in'] as const)"
        :key="way"
        type="button"
        class="min-h-tap rounded-rpos border font-medium transition-colors duration-100 ease-rpos"
        :class="
          direction === way
            ? 'border-primary bg-primary text-primary-contrast'
            : 'border-transparent bg-surface text-content'
        "
        :aria-pressed="direction === way"
        @click="direction = way"
      >
        {{ t(way === "out" ? "drawerCash.out" : "drawerCash.in") }}
      </button>
    </div>

    <AmountKeypad
      :value="amount"
      :label="t('drawerCash.amount')"
      @update="amount = $event"
    />

    <p
      v-if="error"
      role="alert"
      class="mb-3 mt-3 rounded-rpos bg-danger/10 p-3 text-xs text-danger"
    >
      {{ error }}
    </p>

    <button
      type="button"
      class="rpos-pad-done mt-4"
      :disabled="busy || value <= 0"
      @click="confirm"
    >
      {{ t("drawerCash.confirm") }}
    </button>

    <ReasonDialog
      :open="askingReason"
      :title="t('drawerCash.whyTitle')"
      :explain="explain"
      :placeholder="t('drawerCash.whyPlaceholder')"
      :confirm="t('drawerCash.confirm')"
      scope="cash_reason"
      @confirm="onReason"
      @close="askingReason = false"
    />

    <ManagerPinDialog
      :open="askingManager"
      :explain="`${t('drawerCash.needsManager')} ${explain}`"
      :verify="approveWith"
      @approved="onApproved"
      @close="askingManager = false"
    />
  </BaseDialog>
</template>
