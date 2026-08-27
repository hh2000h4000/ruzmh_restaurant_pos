<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import * as paymentApi from "@/api/payment";
import type { PaymentLine, PaymentSummary, TotalsPreview } from "@/api/payment";
import BaseDialog from "@/components/BaseDialog.vue";
import { formatNumber, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Screen 6 — payment.
 *
 * Three columns: methods, discounts, summary (FR-10.1). Every figure comes from
 * the server: the discount is previewed by `preview_totals` before the customer
 * is quoted, and the final amount is the one the Sales Invoice carries
 * (D-018).
 */
const QUICK_DISCOUNTS = [10, 25, 50];

const route = useRoute();
const router = useRouter();
const session = useSessionStore();

const orderName = route.params.orderName as string;

const summary = ref<PaymentSummary | null>(null);
const preview = ref<TotalsPreview | null>(null);
const lines = ref<PaymentLine[]>([]);
const discountType = ref<"percentage" | "amount" | null>(null);
const discountValue = ref(0);
const overrideToken = ref<string | null>(null);
const busy = ref(false);
const failure = ref<string | null>(null);
const done = ref<paymentApi.PaymentResult | null>(null);

// Manager approval (FR-10.4, Screen 9)
const askingPin = ref(false);
const pin = ref("");
const pinReason = ref("");
const pinError = ref<string | null>(null);

const due = computed(() => preview.value?.total_amount ?? summary.value?.total_amount ?? 0);
const paid = computed(() => lines.value.reduce((total, line) => total + (line.amount || 0), 0));
const remaining = computed(() => round(due.value - paid.value));
const tendered = computed(() =>
  lines.value.reduce((total, line) => total + (line.tendered ?? line.amount ?? 0), 0),
);
const change = computed(() => (remaining.value <= 0 ? round(tendered.value - due.value) : 0));

const forcedMethod = computed(
  () => summary.value?.payment_methods.find((method) => method.is_forced)?.payment_method ?? null,
);
const canConfirm = computed(
  () => !busy.value && lines.value.length > 0 && remaining.value <= 0.005 && !done.value,
);
const needsApproval = computed(() => Boolean(preview.value?.requires_override));

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function money(value: number): string {
  return formatNumber(value, 2);
}

onMounted(async () => {
  try {
    summary.value = await paymentApi.getPaymentSummary(orderName);
    if (summary.value.already_paid) {
      failure.value = t("pay.alreadyPaid", { invoice: summary.value.sales_invoice ?? "" });
    }
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
});

/** Re-price on the server whenever the discount changes (FR-10.4). */
watch([discountType, discountValue], async () => {
  overrideToken.value = null;

  if (!discountType.value || !discountValue.value) {
    preview.value = null;
    return;
  }

  try {
    preview.value = await paymentApi.previewTotals(
      orderName,
      discountType.value,
      discountValue.value,
    );
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  }
});

function setQuickDiscount(percentage: number): void {
  if (discountType.value === "percentage" && discountValue.value === percentage) {
    discountType.value = null;
    discountValue.value = 0;
    return;
  }
  discountType.value = "percentage";
  discountValue.value = percentage;
}

function addMethod(method: string): void {
  if (lines.value.some((line) => line.method === method)) return;

  // FR-10.2 — the newly added method takes whatever is still owed.
  lines.value.push({ method, amount: Math.max(remaining.value, 0) });
}

function removeMethod(index: number): void {
  lines.value.splice(index, 1);
}

async function approveDiscount(): Promise<void> {
  if (!summary.value || !preview.value) return;

  pinError.value = null;
  try {
    const approval = await paymentApi.validateDiscountOverride({
      pin: pin.value,
      percentage: preview.value.discount_percentage,
      reason: pinReason.value.trim(),
      branch: session.branch ?? "",
      pos_profile: session.profile?.name ?? "",
      order_name: orderName,
    });

    overrideToken.value = approval.override_token;
    askingPin.value = false;
  } catch (cause) {
    pinError.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    pin.value = "";
  }
}

async function confirm(): Promise<void> {
  if (!canConfirm.value) return;

  if (needsApproval.value && !overrideToken.value) {
    askingPin.value = true;
    return;
  }

  busy.value = true;
  failure.value = null;

  try {
    done.value = await paymentApi.processPayment({
      order_name: orderName,
      payments: lines.value,
      discount_type: discountType.value,
      discount_value: discountValue.value,
      manager_override_token: overrideToken.value,
    });
  } catch (cause) {
    failure.value = cause instanceof Error ? cause.message : String(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex h-full flex-col">
    <header class="flex items-center gap-3 border-b border-line bg-surface px-4 py-3">
      <RouterLink
        :to="{ name: 'order', params: { orderName } }"
        class="rpos-tap inline-flex items-center px-2 text-primary"
      >
        ←
      </RouterLink>
      <h1 class="font-semibold">
        {{ t("pay.title") }}
      </h1>
      <span class="rpos-numeric text-xs text-muted">{{ orderName }}</span>
    </header>

    <!-- Paid: the receipt state, with no way back into an invoiced order. -->
    <section
      v-if="done"
      class="m-auto max-w-sm rounded-rpos bg-surface p-8 text-center shadow-sm"
    >
      <p class="mb-2 text-lg font-semibold text-status-available">
        {{ t("pay.paid") }}
      </p>
      <p class="rpos-numeric mb-1 text-3xl font-bold">
        {{ money(done.total_amount) }}
      </p>
      <p
        v-if="done.change_amount > 0"
        class="rpos-numeric mb-4 text-lg text-status-reserved"
      >
        {{ t("pay.change") }}: {{ money(done.change_amount) }}
      </p>
      <p class="rpos-numeric mb-6 text-sm text-muted">
        {{ done.sales_invoice }}
      </p>
      <button
        type="button"
        class="min-h-tap w-full rounded-rpos bg-primary px-4 font-medium text-primary-contrast"
        @click="router.push({ name: 'home' })"
      >
        {{ t("pay.newOrder") }}
      </button>
    </section>

    <p
      v-else-if="failure"
      role="alert"
      class="m-4 rounded-rpos bg-danger/10 p-4 text-danger"
    >
      {{ failure }}
    </p>

    <div
      v-else-if="summary"
      class="grid flex-1 gap-3 overflow-y-auto p-3 lg:grid-cols-3"
    >
      <!-- 1 — methods -->
      <section class="rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.methods") }}
        </h2>

        <p
          v-if="forcedMethod"
          class="mb-3 rounded-rpos bg-status-reserved/10 p-2 text-xs text-status-reserved"
        >
          {{ t("pay.forcedMethod", { method: forcedMethod ?? "" }) }}
        </p>

        <div class="mb-4 flex flex-wrap gap-2">
          <button
            v-for="method in summary.payment_methods"
            :key="method.payment_method"
            type="button"
            class="min-h-tap rounded-rpos border border-line px-4 text-sm disabled:opacity-40"
            :disabled="lines.some((line) => line.method === method.payment_method)"
            @click="addMethod(method.payment_method)"
          >
            {{ method.payment_method }}
          </button>
        </div>

        <div
          v-for="(line, index) in lines"
          :key="line.method"
          class="mb-3"
        >
          <div class="mb-1 flex items-center justify-between">
            <label
              :for="`amount-${index}`"
              class="text-sm font-medium"
            >{{ line.method }}</label>
            <button
              type="button"
              class="text-xs text-danger"
              @click="removeMethod(index)"
            >
              {{ t("action.remove") }}
            </button>
          </div>
          <input
            :id="`amount-${index}`"
            v-model.number="line.amount"
            type="number"
            step="0.05"
            min="0"
            class="rpos-numeric min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          >
          <label
            :for="`tendered-${index}`"
            class="mt-1 block text-xs text-muted"
          >
            {{ t("pay.received") }}
          </label>
          <input
            :id="`tendered-${index}`"
            v-model.number="line.tendered"
            type="number"
            step="0.05"
            min="0"
            class="rpos-numeric min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          >
        </div>
      </section>

      <!-- 2 — discounts -->
      <section class="rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.discounts") }}
        </h2>

        <div class="mb-4 flex gap-2">
          <button
            v-for="percentage in QUICK_DISCOUNTS"
            :key="percentage"
            type="button"
            class="min-h-tap flex-1 rounded-rpos border text-sm"
            :class="
              discountType === 'percentage' && discountValue === percentage
                ? 'border-primary bg-primary text-primary-contrast'
                : 'border-line'
            "
            @click="setQuickDiscount(percentage)"
          >
            {{ percentage }}%
          </button>
        </div>

        <label
          for="manual-discount"
          class="mb-1 block text-sm font-medium"
        >{{ t("pay.manualDiscount") }}</label>
        <div class="flex gap-2">
          <input
            id="manual-discount"
            v-model.number="discountValue"
            type="number"
            min="0"
            step="0.5"
            class="rpos-numeric min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          >
          <select
            v-model="discountType"
            :aria-label="t('pay.discountType')"
            class="min-h-tap rounded-rpos border border-line bg-background px-2"
          >
            <option :value="null">
              —
            </option>
            <option value="percentage">
              %
            </option>
            <option value="amount">
              {{ t("currency.sar") }}
            </option>
          </select>
        </div>

        <p
          v-if="needsApproval"
          class="mt-3 rounded-rpos bg-status-reserved/10 p-2 text-xs text-status-reserved"
        >
          {{ t("pay.exceedsLimit", { limit: `${preview?.max_discount_percentage ?? 0}%` }) }}
          <span
            v-if="overrideToken"
            class="font-medium text-status-available"
          >{{ t("pay.authorized") }} ✓</span>
        </p>

        <p class="mt-4 text-xs text-muted">
          {{ t("pay.loyaltySoon") }}
        </p>
      </section>

      <!-- 3 — summary -->
      <section class="flex flex-col rounded-rpos bg-surface p-4">
        <h2 class="mb-3 text-sm font-medium text-muted">
          {{ t("pay.summary") }}
        </h2>

        <dl class="space-y-1 text-sm">
          <div class="flex justify-between">
            <dt>{{ t("totals.subtotal") }}</dt>
            <dd class="rpos-numeric">
              {{ money(preview?.subtotal ?? summary.subtotal) }}
            </dd>
          </div>
          <div
            v-if="(preview?.discount_amount ?? summary.discount_amount) > 0"
            class="flex justify-between text-status-available"
          >
            <dt>{{ t("totals.discount") }}</dt>
            <dd class="rpos-numeric">
              −{{ money(preview?.discount_amount ?? summary.discount_amount) }}
            </dd>
          </div>
          <div class="flex justify-between">
            <dt>{{ t("totals.tax") }}</dt>
            <dd class="rpos-numeric">
              {{ money(preview?.tax_amount ?? summary.tax_amount) }}
            </dd>
          </div>
          <div class="flex justify-between border-t border-line pt-2 text-lg font-bold">
            <dt>{{ t("totals.total") }}</dt>
            <dd class="rpos-numeric">
              {{ money(due) }}
            </dd>
          </div>
        </dl>

        <div class="mt-4 space-y-1 text-sm">
          <div
            v-if="remaining > 0"
            class="flex justify-between text-status-reserved"
          >
            <span>{{ t("pay.remaining") }}</span>
            <span class="rpos-numeric">{{ money(remaining) }}</span>
          </div>
          <div
            v-if="change > 0"
            class="flex justify-between text-lg font-semibold"
          >
            <span>{{ t("pay.change") }}</span>
            <span class="rpos-numeric">{{ money(change) }}</span>
          </div>
        </div>

        <button
          type="button"
          class="mt-auto min-h-tap w-full rounded-rpos bg-primary px-4 text-base font-medium text-primary-contrast disabled:opacity-50"
          :disabled="!canConfirm"
          @click="confirm"
        >
          {{ busy ? "…" : `✅ ${t("pay.confirm")}` }}
        </button>
      </section>
    </div>

    <!-- Screen 9 — manager authorisation -->
    <BaseDialog
      :open="askingPin"
      :title="`🔐 ${t('pay.needsManager')}`"
      @close="askingPin = false"
    >
      <p class="mb-3 text-sm text-muted">
        {{ t("pay.discountExceeds", { value: `${preview?.discount_percentage ?? 0}%` }) }}
      </p>
      <label
        for="pin"
        class="mb-1 block text-sm font-medium"
      >{{ t("pay.managerPin") }}</label>
      <input
        id="pin"
        v-model="pin"
        type="password"
        inputmode="numeric"
        maxlength="4"
        autocomplete="off"
        class="rpos-numeric mb-3 min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-center text-2xl tracking-widest"
      >
      <label
        for="pin-reason"
        class="mb-1 block text-sm font-medium"
      >{{ t("pay.reasonRequired") }}</label>
      <input
        id="pin-reason"
        v-model="pinReason"
        type="text"
        class="mb-4 min-h-tap w-full rounded-rpos border border-line bg-background px-3"
      >
      <p
        v-if="pinError"
        role="alert"
        class="mb-3 text-sm text-danger"
      >
        {{ pinError }}
      </p>
      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="askingPin = false"
        >
          {{ t("action.cancel") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-50"
          :disabled="pin.length !== 4 || !pinReason.trim()"
          @click="approveDiscount"
        >
          {{ t("action.authorize") }}
        </button>
      </div>
    </BaseDialog>
  </main>
</template>
