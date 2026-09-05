<script setup lang="ts">
import { computed, ref, watch } from "vue";

import {
  addCustomerAddress,
  createCustomer,
  getCustomer,
  searchCustomers,
  type CustomerDetail,
  type CustomerSummary,
} from "@/api/customer";
import AppIcon from "@/components/AppIcon.vue";
import BaseDialog from "@/components/BaseDialog.vue";
import DigitPad from "@/components/DigitPad.vue";
import { t } from "@/i18n";

/**
 * Who the order is for (FR-2.1 step 4, D-050).
 *
 * **One field, and the search is also the way in.** The cashier types the
 * number. If the person is there they appear; if they are not, the same number
 * becomes a new customer without retyping it. A separate "Add customer" button
 * beside a search box is the wrong shape for this: it invites creating before
 * looking, and a second record on a number that already exists splits one
 * person's delivery history in half — which is exactly what the backend refuses
 * and what this screen must not make a cashier want to work around.
 *
 * **The number, not the name.** "محمد" repeats a hundred times in any
 * restaurant's database and a phone does not. A name search exists for the till
 * that has a regular's name and not their number, and it is the weaker key on
 * purpose.
 *
 * **The address is offered, never demanded.** No order type carries a
 * "requires an address" flag, so this screen does not invent one: for a type
 * that insists on a customer it shows the addresses and lets the cashier skip.
 * A screen that refused to continue over a rule the server does not enforce
 * would be a rule nobody could find or change.
 */
const props = defineProps<{
  open: boolean;
  /** Already attached, so the dialog opens knowing who it is looking at. */
  customer?: string | null;
  /** Show the address step after choosing — see the note on the address above. */
  withAddress?: boolean;
  /** The type cannot be opened without one, so there is nothing to clear to. */
  required?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  select: [payload: { customer: string; deliveryAddress: string | null }];
  clear: [];
}>();

/** Where the one dialog is: looking, making, or saying where it goes. */
const step = ref<"search" | "create" | "address">("search");

const term = ref("");
const results = ref<CustomerSummary[]>([]);
const searching = ref(false);
const busy = ref(false);
const error = ref<string | null>(null);
const chosen = ref<CustomerDetail | null>(null);

const newPhone = ref("");
const newName = ref("");
const newAddress = ref("");
const addressLine = ref("");
const addingAddress = ref(false);

/** Digits only — a number is the same number however it was punctuated. */
const digits = computed(() => term.value.replace(/\D/g, ""));

/**
 * Three digits is where a search stops matching the whole database, and it is
 * also where the difference between a number and a name becomes readable.
 */
const byPhone = computed(() => digits.value.length >= 3);

const title = computed(() => {
  if (step.value === "create") return t("customer.createTitle");
  if (step.value === "address") return t("customer.addressTitle");
  return t("customer.title");
});

function message(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

// --------------------------------------------------------------------------
// Looking
// --------------------------------------------------------------------------

let timer: ReturnType<typeof setTimeout> | undefined;

watch(term, (value) => {
  clearTimeout(timer);

  const query = value.trim();
  if (query.length < 3) {
    results.value = [];
    searching.value = false;
    return;
  }

  // A request per keystroke would send ten for one number and let an early
  // answer land after a later one.
  searching.value = true;
  timer = setTimeout(() => void look(query), 250);
});

async function look(query: string): Promise<void> {
  try {
    results.value = await searchCustomers(byPhone.value ? { phone: query } : { name: query });
    error.value = null;
  } catch (cause) {
    error.value = message(cause);
    results.value = [];
  } finally {
    searching.value = false;
  }
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) return;

    clearTimeout(timer);
    step.value = "search";
    term.value = "";
    results.value = [];
    searching.value = false;
    error.value = null;
    newPhone.value = "";
    newName.value = "";
    newAddress.value = "";
    addressLine.value = "";
    addingAddress.value = false;
    chosen.value = null;

    if (!props.customer) return;

    // Opening on an order that already has somebody: show who, rather than an
    // empty box the cashier has to fill to find out.
    chosen.value = await load(props.customer);
    if (chosen.value && props.withAddress) step.value = "address";
  },
);

async function load(customer: string): Promise<CustomerDetail | null> {
  busy.value = true;
  try {
    return await getCustomer(customer);
  } catch (cause) {
    error.value = message(cause);
    return null;
  } finally {
    busy.value = false;
  }
}

async function choose(row: CustomerSummary): Promise<void> {
  const detail = await load(row.name);
  if (!detail) return;

  chosen.value = detail;

  if (!props.withAddress) {
    commit(null);
    return;
  }

  // One address is not a choice; asking anyway is a tap for nothing.
  if (detail.addresses.length === 1) {
    commit(detail.addresses[0].name);
    return;
  }

  step.value = "address";
  addingAddress.value = detail.addresses.length === 0;
}

function commit(deliveryAddress: string | null): void {
  if (!chosen.value) return;
  emit("select", { customer: chosen.value.name, deliveryAddress });
}

// --------------------------------------------------------------------------
// Making
// --------------------------------------------------------------------------

function startCreate(): void {
  // Whatever was typed is already the answer to one of the two questions.
  newPhone.value = byPhone.value ? digits.value : "";
  newName.value = byPhone.value ? "" : term.value.trim();
  newAddress.value = "";
  error.value = null;
  step.value = "create";
}

const canSave = computed(() => Boolean(newPhone.value.trim() && newName.value.trim()));

async function saveNew(): Promise<void> {
  if (!canSave.value || busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    const created = await createCustomer({
      phone: newPhone.value.trim(),
      customer_name: newName.value.trim(),
      address: newAddress.value.trim() ? { address_line1: newAddress.value.trim() } : null,
    });

    chosen.value = created;
    commit(created.addresses[0]?.name ?? null);
  } catch (cause) {
    // Very often "somebody already uses this number" — which is the duplicate
    // this screen exists to prevent, so it is shown and the cashier searches.
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

// --------------------------------------------------------------------------
// Where it goes
// --------------------------------------------------------------------------

function addressText(address: { address_line1: string | null; city: string | null }): string {
  return [address.address_line1, address.city].filter(Boolean).join(t("common.listSeparator"));
}

async function saveAddress(): Promise<void> {
  if (!chosen.value || !addressLine.value.trim() || busy.value) return;

  busy.value = true;
  error.value = null;
  try {
    const result = await addCustomerAddress({
      customer: chosen.value.name,
      address: { address_line1: addressLine.value.trim() },
    });

    chosen.value.addresses = result.addresses;
    addingAddress.value = false;
    addressLine.value = "";
    commit(result.address);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseDialog
    :open="open"
    :title="title"
    @close="emit('close')"
  >
    <p
      v-if="error"
      role="alert"
      class="mb-3 rounded-rpos bg-danger/10 p-3 text-sm text-danger"
    >
      {{ error }}
    </p>

    <!-- ------------------------------------------------------------------ -->
    <!-- Looking                                                            -->
    <!-- ------------------------------------------------------------------ -->
    <template v-if="step === 'search'">
      <!-- Who is on the order now, and the way to take them off. Shown first
           because "change the customer" starts with knowing who it is. -->
      <div
        v-if="chosen"
        class="mb-3 flex items-center gap-3 rounded-rpos bg-background p-3"
      >
        <AppIcon
          name="user"
          :size="20"
        />
        <span class="min-w-0 flex-1">
          <span class="block truncate font-semibold">{{ chosen.customer_name }}</span>
          <span
            v-if="chosen.mobile_no"
            class="rpos-numeric block truncate text-sm text-muted"
            dir="ltr"
          >{{ chosen.mobile_no }}</span>
        </span>
        <button
          v-if="!required"
          type="button"
          class="min-h-tap shrink-0 rounded-rpos px-3 text-sm font-semibold text-danger transition duration-200 ease-rpos hover:bg-danger/10"
          @click="emit('clear')"
        >
          {{ t("customer.remove") }}
        </button>
      </div>

      <p class="mb-3 text-sm text-muted">
        {{ t("customer.body") }}
      </p>

      <div class="mb-3 flex items-center gap-2 rounded-rpos border border-line bg-background px-3">
        <AppIcon
          name="search"
          :size="20"
          class="shrink-0 text-muted"
        />
        <input
          v-model="term"
          type="search"
          inputmode="tel"
          autocomplete="off"
          class="rpos-numeric min-h-tap w-full bg-transparent text-lg"
          dir="ltr"
          :placeholder="t('customer.searchPlaceholder')"
        >
      </div>

      <!-- The results box keeps its height whether it is empty, loading or
           full, so the pad below it does not jump under the finger. -->
      <div class="mb-3 max-h-56 min-h-[7rem] overflow-y-auto rounded-rpos bg-background">
        <button
          v-for="row in results"
          :key="row.name"
          type="button"
          class="flex min-h-tap w-full items-center gap-3 border-b border-line px-3 text-start last:border-b-0 transition duration-200 ease-rpos hover:bg-surface disabled:opacity-40"
          :disabled="busy"
          @click="choose(row)"
        >
          <AppIcon
            name="user"
            :size="18"
            class="shrink-0 text-muted"
          />
          <span class="min-w-0 flex-1">
            <span class="block truncate font-semibold">{{ row.customer_name }}</span>
            <span
              v-if="row.mobile_no"
              class="rpos-numeric block truncate text-sm text-muted"
              dir="ltr"
            >{{ row.mobile_no }}</span>
          </span>
        </button>

        <p
          v-if="searching"
          class="p-4 text-center text-sm text-muted"
        >
          {{ t("common.loading") }}
        </p>

        <p
          v-else-if="!results.length && term.trim().length >= 3"
          class="p-4 text-center text-sm text-muted"
        >
          {{ t("customer.noResults") }}
        </p>

        <p
          v-else-if="!results.length"
          class="p-4 text-center text-sm text-muted"
        >
          {{ t("customer.searchHint") }}
        </p>
      </div>

      <!-- The way in, and it carries what was already typed. -->
      <button
        v-if="term.trim().length >= 3 && !searching"
        type="button"
        class="mb-3 flex min-h-tap w-full items-center justify-center gap-2 rounded-rpos border border-dashed border-primary/50 text-sm font-semibold text-primary transition duration-200 ease-rpos hover:bg-primary/5"
        @click="startCreate"
      >
        <AppIcon
          name="plus"
          :size="18"
        />
        {{ byPhone ? t("customer.createWith", { phone: digits }) : t("customer.createTitle") }}
      </button>

      <DigitPad
        class="mb-4"
        :value="digits"
        :max-length="14"
        @update="term = $event"
      />

      <button
        type="button"
        class="min-h-tap w-full rounded-rpos border border-line"
        @click="emit('close')"
      >
        {{ t("action.undo") }}
      </button>
    </template>

    <!-- ------------------------------------------------------------------ -->
    <!-- Making                                                             -->
    <!-- ------------------------------------------------------------------ -->
    <template v-else-if="step === 'create'">
      <label class="mb-3 block">
        <span class="mb-1 block text-sm font-semibold text-muted">{{ t("customer.phone") }}</span>
        <input
          v-model="newPhone"
          type="tel"
          inputmode="tel"
          class="rpos-numeric min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-lg"
          dir="ltr"
          :placeholder="t('customer.searchPlaceholder')"
        >
      </label>

      <label class="mb-3 block">
        <span class="mb-1 block text-sm font-semibold text-muted">{{ t("customer.name") }}</span>
        <input
          v-model="newName"
          type="text"
          class="min-h-tap w-full rounded-rpos border border-line bg-background px-3 text-lg"
          :placeholder="t('customer.namePlaceholder')"
          @keyup.enter="saveNew"
        >
      </label>

      <label class="mb-4 block">
        <span class="mb-1 block text-sm font-semibold text-muted">{{ t("customer.address") }}</span>
        <input
          v-model="newAddress"
          type="text"
          class="min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          :placeholder="t('customer.addressPlaceholder')"
          @keyup.enter="saveNew"
        >
      </label>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="step = 'search'"
        >
          {{ t("action.back") }}
        </button>
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-bold text-primary-contrast disabled:opacity-40"
          :disabled="!canSave || busy"
          @click="saveNew"
        >
          {{ t("customer.save") }}
        </button>
      </div>
    </template>

    <!-- ------------------------------------------------------------------ -->
    <!-- Where it goes                                                      -->
    <!-- ------------------------------------------------------------------ -->
    <template v-else>
      <p class="mb-3 text-sm text-muted">
        {{ t("customer.addressBody") }}
      </p>

      <div
        v-if="chosen?.addresses.length"
        class="mb-3 overflow-hidden rounded-rpos bg-background"
      >
        <button
          v-for="address in chosen.addresses"
          :key="address.name"
          type="button"
          class="flex min-h-tap w-full items-center gap-3 border-b border-line px-3 text-start last:border-b-0 transition duration-200 ease-rpos hover:bg-surface"
          :disabled="busy"
          @click="commit(address.name)"
        >
          <AppIcon
            name="home"
            :size="18"
            class="shrink-0 text-muted"
          />
          <span class="min-w-0 flex-1 truncate">{{ addressText(address) }}</span>
        </button>
      </div>

      <p
        v-else-if="!addingAddress"
        class="mb-3 rounded-rpos bg-background p-4 text-center text-sm text-muted"
      >
        {{ t("customer.noAddresses") }}
      </p>

      <div
        v-if="addingAddress"
        class="mb-3"
      >
        <input
          v-model="addressLine"
          type="text"
          class="min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          :placeholder="t('customer.addressPlaceholder')"
          @keyup.enter="saveAddress"
        >
        <button
          type="button"
          class="mt-2 min-h-tap w-full rounded-rpos bg-primary font-bold text-primary-contrast disabled:opacity-40"
          :disabled="!addressLine.trim() || busy"
          @click="saveAddress"
        >
          {{ t("action.save") }}
        </button>
      </div>

      <button
        v-else
        type="button"
        class="mb-4 flex min-h-tap w-full items-center justify-center gap-2 rounded-rpos border border-dashed border-primary/50 text-sm font-semibold text-primary transition duration-200 ease-rpos hover:bg-primary/5"
        @click="addingAddress = true"
      >
        <AppIcon
          name="plus"
          :size="18"
        />
        {{ t("customer.addAddress") }}
      </button>

      <div class="flex gap-2">
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos border border-line"
          @click="step = 'search'"
        >
          {{ t("action.back") }}
        </button>
        <!-- Skipping is allowed because no rule on the server forbids it; a
             takeaway attached to a regular has no address to give. -->
        <button
          type="button"
          class="min-h-tap flex-1 rounded-rpos bg-primary font-bold text-primary-contrast disabled:opacity-40"
          :disabled="busy"
          @click="commit(null)"
        >
          {{ t("customer.withoutAddress") }}
        </button>
      </div>
    </template>
  </BaseDialog>
</template>
