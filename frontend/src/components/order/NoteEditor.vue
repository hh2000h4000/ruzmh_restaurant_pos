<script setup lang="ts">
import { computed } from "vue";

import { pick, t } from "@/i18n";
import { useSessionStore } from "@/stores/session";

/**
 * Writing a note, mostly without writing (FR-2.9).
 *
 * Typing Arabic on a touch screen in the middle of a lunch rush is the slowest
 * thing a cashier does, and the notes a kitchen hears are the same twelve every
 * day. So the saved ones are chips: tap to add, tap again to take back.
 *
 * The free-text box stays. A restaurant cannot list every note in advance, and
 * a screen that only offers a list turns "no coriander, he's allergic" into an
 * argument at the counter.
 *
 * **Scope is not cosmetic.** An `item` note travels with its line to the one
 * station that cooks it; an `order` note is printed on every station's ticket.
 * Showing the wrong list here would let a cashier put an allergy where only the
 * grill can see it.
 */
const props = defineProps<{
  /** Which saved notes to offer. */
  scope: "item" | "order";
  placeholder?: string;
}>();

const text = defineModel<string>({ default: "" });

const session = useSessionStore();

const chips = computed(() =>
  (session.data?.quick_notes ?? []).filter(
    (note) => note.scope === props.scope || note.scope === "both",
  ),
);

/** What a chip contributes to the text, in the language on screen. */
function label(note: { title: string; title_ar: string }): string {
  return pick(note.title_ar, note.title);
}

/**
 * The separator is the language's, not a character typed here.
 *
 * Arabic joins with "،" and English with ",", and hardcoding either would put
 * the wrong punctuation on a kitchen ticket — which is what the project's
 * no-Arabic-literals rule is for.
 */
const separator = computed(() => t("common.listSeparator").trim());

const parts = computed(() =>
  text.value
    .split(separator.value)
    .map((part) => part.trim())
    .filter(Boolean),
);

function isOn(note: { title: string; title_ar: string }): boolean {
  return parts.value.includes(label(note));
}

/**
 * Chips edit the same text the box holds, rather than living beside it.
 *
 * One value means what the cashier sees is what the kitchen gets — no reconciling
 * a list against a box that disagrees with it.
 */
function toggle(note: { title: string; title_ar: string }): void {
  const value = label(note);
  const next = isOn(note)
    ? parts.value.filter((part) => part !== value)
    : [...parts.value, value];

  text.value = next.join(t("common.listSeparator"));
}
</script>

<template>
  <div>
    <div
      v-if="chips.length"
      class="mb-3 flex flex-wrap gap-2"
    >
      <button
        v-for="note in chips"
        :key="note.name"
        type="button"
        class="min-h-tap rounded-full px-4 text-sm font-medium transition duration-200 ease-rpos"
        :class="
          isOn(note)
            ? 'bg-primary text-primary-contrast shadow-card'
            : 'bg-background text-muted hover:text-content'
        "
        :aria-pressed="isOn(note)"
        @click="toggle(note)"
      >
        {{ label(note) }}
      </button>
    </div>

    <textarea
      v-model="text"
      rows="2"
      class="w-full resize-none rounded-rpos border border-line bg-background px-3 py-2 outline-none transition duration-200 ease-rpos focus:bg-surface focus:ring-2 focus:ring-primary/30"
      :placeholder="placeholder ?? t('note.placeholder')"
    />
  </div>
</template>
