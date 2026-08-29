<script setup lang="ts">
import { computed } from "vue";

import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { dateOnly, t, type MessageKey } from "@/i18n";
import { useSessionStore } from "@/stores/session";
import { useShiftStore } from "@/stores/shift";

/**
 * The till's occasional operations, in a sheet above the bar (D-048).
 *
 * **Why a menu and not more places.** Closing a drawer and ending a day are
 * things a cashier does twice a shift; a pane each would be two panes nobody
 * opens during a rush, taking room from the four that are used constantly. It
 * is `D-037` again — a short row of what is reached without looking, and
 * everything else one deliberate tap behind.
 *
 * **Only what exists.** The reference system lists eleven entries; we have
 * three. Nine disabled rows promising unbuilt screens is the mistake this
 * project has avoided from the start, so the list grows as features land rather
 * than starting full of ghosts.
 *
 * It hangs from the **end** of the bar, because that is where its own button
 * is — the last entry. A sheet opening at the other edge points at nothing.
 */
export interface MenuEntry {
  key: string;
  label: MessageKey;
  icon: IconName;
  /** Extra detail on the row — a date, a name — when it helps. */
  detail?: string;
  destructive?: boolean;
}

defineProps<{ open: boolean }>();
const emit = defineEmits<{ select: [key: string]; close: [] }>();

const session = useSessionStore();
const shift = useShiftStore();

const entries = computed<MenuEntry[]>(() => {
  const rows: MenuEntry[] = [{ key: "home", label: "shift.goHome", icon: "home" }];

  if (!shift.dayOpen) {
    rows.push({ key: "openTill", label: "shift.openTill", icon: "card" });
    return rows;
  }

  if (shift.tillOpen && shift.state?.till.is_mine !== false) {
    rows.push({ key: "closeTill", label: "shift.closeTill", icon: "card" });
  } else if (!shift.tillOpen) {
    rows.push({ key: "openTill", label: "shift.openTill", icon: "card" });
  }

  rows.push({
    key: "closeDay",
    label: "shift.closeDay",
    icon: "calendar",
    // The date, because "end of day" is ambiguous at one in the morning.
    detail: shift.state?.day.opened_at ? dateOnly(shift.state.day.opened_at) : undefined,
    destructive: true,
  });

  return rows;
});

/** Who has the drawer, when it is not this cashier — worth saying, not hiding. */
const heldBy = computed(() =>
  shift.tillHeldByOther ? shift.state?.till.user_name || shift.state?.till.user : null,
);
</script>

<template>
  <div
    v-if="open"
    class="absolute bottom-full z-30 mb-2 w-72 overflow-hidden rounded-rpos border border-line bg-surface shadow-lift end-0"
  >
    <p
      v-if="heldBy"
      class="border-b border-line bg-background px-4 py-2 text-xs text-muted"
    >
      {{ t("shift.heldBy", { name: heldBy }) }}
    </p>

    <button
      v-for="entry in entries"
      :key="entry.key"
      type="button"
      class="flex min-h-tap w-full items-center gap-3 px-4 text-start text-sm font-medium transition duration-200 ease-rpos hover:bg-background"
      :class="entry.destructive ? 'text-danger' : ''"
      @click="emit('select', entry.key)"
    >
      <AppIcon
        :name="entry.icon"
        :size="20"
      />
      <span class="min-w-0 flex-1 truncate">{{ t(entry.label) }}</span>
      <span
        v-if="entry.detail"
        class="rpos-numeric shrink-0 text-xs text-muted"
      >{{ entry.detail }}</span>
    </button>

    <p class="border-t border-line px-4 py-2 text-xs text-muted">
      {{ session.data?.user_name || session.data?.user }}
    </p>
  </div>
</template>
