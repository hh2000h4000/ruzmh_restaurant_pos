<script setup lang="ts">
import { computed, ref, watch } from "vue";

import BaseDialog from "@/components/BaseDialog.vue";
import CodePad from "@/components/order/CodePad.vue";
import { pick, t } from "@/i18n";
import { useTypeFieldsStore } from "@/stores/typeFields";

/**
 * The order type's questions — "App Order No" and whatever else a restaurant
 * adds to a type (FR-1.2, `D-409`). One dialog for opening and for converting,
 * because it is one question: what does this type need to know?
 *
 * The keys under the finger are `CodePad`'s, shown only on a till with no
 * keyboard of its own (`D-250`, `D-277`): a platform's order number is read off
 * the tablet beside the till and typed here.
 */
const store = useTypeFieldsStore();

const values = ref<Record<string, string>>({});
/** The field the pad types into. */
const active = ref(0);

watch(
  () => store.asking,
  (asking) => {
    values.value = Object.fromEntries((asking?.fields ?? []).map((field) => [field.label, ""]));
    active.value = 0;
  },
);

const fields = computed(() => store.asking?.fields ?? []);
const typing = computed(() => fields.value[active.value]);

/** The server checks again; this only keeps the button honest. */
const complete = computed(() =>
  fields.value.every((field) => !field.is_required || (values.value[field.label] ?? "").trim() !== ""),
);

function set(label: string, value: string): void {
  values.value = { ...values.value, [label]: value };
}

function send(): void {
  if (!complete.value) return;
  const answers = Object.fromEntries(
    Object.entries(values.value)
      .map(([label, value]) => [label, value.trim()])
      .filter(([, value]) => value !== ""),
  );
  store.answer(answers);
}
</script>

<template>
  <BaseDialog
    :open="Boolean(store.asking)"
    :title="store.asking ? pick(store.asking.type.title_ar, store.asking.type.title) : ''"
    @close="store.answer(null)"
  >
    <div class="mb-4 grid gap-3">
      <label
        v-for="(field, index) in fields"
        :key="field.label"
        class="grid gap-1"
      >
        <span class="text-sm font-medium">
          {{ pick(field.label_ar, field.label) }}
          <span
            v-if="field.is_required"
            class="text-danger"
            :aria-label="t('typeFields.required')"
          >*</span>
        </span>

        <select
          v-if="field.type === 'select'"
          :value="values[field.label]"
          class="min-h-tap w-full rounded-rpos border border-line bg-background px-3"
          @change="set(field.label, ($event.target as HTMLSelectElement).value)"
        >
          <option value="" />
          <option
            v-for="option in field.options"
            :key="option"
            :value="option"
          >
            {{ option }}
          </option>
        </select>

        <input
          v-else
          :value="values[field.label]"
          :inputmode="field.type === 'number' ? 'numeric' : 'text'"
          type="text"
          autocomplete="off"
          dir="ltr"
          class="min-h-tap w-full rounded-rpos border bg-background p-3 text-center text-lg tracking-wider"
          :class="active === index ? 'border-primary' : 'border-line'"
          :placeholder="field.placeholder ?? ''"
          @focus="active = index"
          @input="set(field.label, ($event.target as HTMLInputElement).value)"
          @keyup.enter="send"
        >
      </label>
    </div>

    <CodePad
      v-if="typing && typing.type !== 'select'"
      class="mb-3"
      :value="values[typing.label] ?? ''"
      @update="set(typing.label, $event)"
    />

    <div class="flex gap-2">
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos border border-line"
        @click="store.answer(null)"
      >
        {{ t("action.cancel") }}
      </button>
      <button
        type="button"
        class="min-h-tap flex-1 rounded-rpos bg-primary font-medium text-primary-contrast disabled:opacity-40"
        :disabled="!complete"
        @click="send"
      >
        {{ t("typeFields.continue") }}
      </button>
    </div>
  </BaseDialog>
</template>
