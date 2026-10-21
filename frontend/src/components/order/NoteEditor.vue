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
 *
 * **Reasons are the same question** (`D-239`). *Why was this voided* and *why
 * was this bill cancelled* are typed on a touch screen, in the rush, by
 * somebody with a customer waiting — and the answers are the same handful every
 * day. So they are chips from the same list a manager keeps, and the box stays
 * for the one that is not on it. `both` is a note scope only: a note offered on
 * items and orders is not a reason for voiding anything.
 */
const props = defineProps<{
  /** Which saved lines to offer. */
  scope: "item" | "order" | "void_reason" | "cancel_reason" | "cash_reason";
  placeholder?: string;
  /** One line, not a list — a reason is one sentence (`D-239`). */
  single?: boolean;
}>();

const text = defineModel<string>({ default: "" });

const session = useSessionStore();

const notesScope = computed(() => props.scope === "item" || props.scope === "order");

const chips = computed(() =>
  (session.data?.quick_notes ?? []).filter(
    (note) => note.scope === props.scope || (notesScope.value && note.scope === "both"),
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

  // A reason replaces rather than accumulates: "customer changed their mind،
  // wrong item" is two answers to one question, and the audit log reads worse
  // for it (`D-239`).
  if (props.single) {
    text.value = isOn(note) ? "" : value;
    return;
  }

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
      class="mb-3 grid max-h-[10.5rem] grid-cols-2 gap-2 overflow-y-auto sm:grid-cols-3"
    >
      <!-- A grid of a fixed height (`D-380`): more saved notes scroll inside
           this box, and never push the dialog's own buttons off the screen. -->
      <button
        v-for="note in chips"
        :key="note.name"
        type="button"
        class="rpos-chip min-h-tap truncate rounded px-3 text-sm font-medium transition duration-100 ease-rpos"
        :class="isOn(note) ? 'bg-primary text-primary-contrast' : ''"
        :aria-pressed="isOn(note)"
        @click="toggle(note)"
      >
        {{ label(note) }}
      </button>
    </div>

    <textarea
      v-model="text"
      rows="1"
      class="rpos-field w-full resize-none rounded px-3 py-3 outline-none transition duration-200 ease-rpos focus:ring-2 focus:ring-primary/30"
      :placeholder="placeholder ?? t('note.placeholder')"
    />
  </div>
</template>
