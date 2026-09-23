<script setup lang="ts">
import { computed } from "vue";

import AppIcon, { type IconName } from "@/components/AppIcon.vue";
import { dateOnly, sinceWhen, t, type MessageKey } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
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
 * four. Nine disabled rows promising unbuilt screens is the mistake this
 * project has avoided from the start, so the list grows as features land rather
 * than starting full of ghosts.
 *
 * There is no "till screen" entry any more: the orders screen **is** the till
 * screen (D-055), so a row pointing at it would point at the page it is on.
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
// No `close` here: the sheet is opened and dismissed by the bar that owns it,
// and an event nothing ever emitted was a way out that did not exist (§5.5).
const emit = defineEmits<{ select: [key: string] }>();

const session = useSessionStore();
const shift = useShiftStore();
const auth = useAuthStore();

/**
 * Which till this is, and where it stands (`D-240`).
 *
 * Nothing on the selling screen said it. A manager walking the floor, or a
 * cashier on a device that was paired to the wrong terminal, had no way to ask
 * — and the answer decides which drawer their sale lands in and which branch's
 * day it belongs to. It goes here, one deliberate tap behind the bar, rather
 * than into a header that a phone-width till cannot spare (`D-221`).
 */
const whereWeAre = computed(() => {
  const branch = session.data?.branch;
  return [branch?.branch || branch?.name, session.profile?.name].filter(Boolean).join(" · ");
});

const restaurant = computed(() => session.profile?.company ?? "");

/**
 * Clocking out where the day is ended (`FR-8.4` step 4).
 *
 * It was only on the sign-in screen, which is the wrong end of the shift: a
 * cashier finishing up closes the drawer from this menu, and had to sign out
 * and meet the PIN pad again to say they had gone home. The two are one errand
 * and they belong in one place.
 *
 * **Above the drawer entries, not among them.** Going home is a person and a
 * till shift is a drawer (`D-057`); the row is separated so the menu does not
 * quietly teach that ending one ends the other.
 *
 * Absent for anyone with no `Employee` behind their login. The welcome screen
 * says why to them instead (`D-184`) — here it would be a disabled row in a
 * list of live ones, which reads as a fault rather than as a rule.
 */
const attendance = computed<MenuEntry | null>(() => {
  // **The same rule the welcome screen reads** (`D-177`, §5.5). This menu used
  // to decide for itself, from `clockedIn` alone, and it sits directly above
  // "close the till" — so it offered a cashier the way home while the drawer
  // they are answerable for was still open. The entry appears once the drawer
  // is counted, which is the order the shift actually runs in.
  //
  // **Going home only — never arriving** (`D-185`). Clocking in belongs to the
  // welcome screen, which everyone now passes through (`D-184`) and which drops
  // them here the moment they tap it (`D-179`). An entry offering to clock in
  // *from inside the till* is a second door into a room they are standing in.
  if (auth.punchOnOffer !== "out") return null;

  return {
    key: "clock",
    label: "auth.clockOut",
    icon: "hourglass",
    // Since when, because "am I still clocked in from yesterday?" is the
    // question this row is usually opened to answer — and it used to answer it
    // with a bare time, which is the one shape that cannot (`D-178`).
    detail:
      auth.clockedIn && auth.attendance?.since ? sinceWhen(auth.attendance.since) : undefined,
  };
});

/**
 * The day's bookings (`D-191`).
 *
 * **Here, not on the bar.** The bar holds what is reached without looking, and
 * a sixth entry there broke it onto a second line — the user saw it and moved
 * it here. Offered with the day closed too: tomorrow's booking is taken on the
 * phone before anybody has opened a drawer.
 */
const BOOKINGS: MenuEntry = { key: "reservations", label: "nav.reservations", icon: "calendar" };

const entries = computed<MenuEntry[]>(() => {
  const rows: MenuEntry[] = [];
  if (attendance.value) rows.push(attendance.value);

  if (!shift.dayOpen) {
    rows.push({ key: "openTill", label: "shift.openTill", icon: "card" });
    rows.push(BOOKINGS);
    rows.push({ key: "logout", label: "home.logout", icon: "logout", destructive: true });
    return rows;
  }

  if (shift.tillOpen && shift.state?.till.is_mine !== false) {
    rows.push({ key: "closeTill", label: "shift.closeTill", icon: "card" });
  } else if (!shift.tillOpen) {
    rows.push({ key: "openTill", label: "shift.openTill", icon: "card" });
  }

  // D-219 — the drawer's report, printed without closing it: a cashier stepping
  // away prints it, and prints it again on coming back. Offered for a shared
  // drawer held by someone else too, because that is the drawer it checks.
  if (shift.tillOpen) {
    rows.push({ key: "viewReport", label: "shift.reportTitle", icon: "receipt" });
    // `D-245` — notes out for a bag of ice, or in from the safe. Offered to every
    // cashier: without the permission the screen asks for a manager's PIN, which
    // is the same shape a discount over their ceiling takes.
    rows.push({ key: "drawerCash", label: "drawerCash.title", icon: "card" });
  }

  rows.push(BOOKINGS);

  // Who is at work — for whoever may read a report. Above the destructive pair
  // and below the drawer, because it changes nothing: it only answers.
  if (session.can("can_access_reports")) {
    rows.push({ key: "roster", label: "roster.title", icon: "hourglass" });
  }

  // FR-13 — the screen facing the guest, opened in a window of its own and
  // dragged to the second monitor. Here rather than on the bill: it is set up
  // once when the counter is opened, like the drawer, and no permission guards
  // it because it shows only what the guest is already being told (`D-162`).
  rows.push({ key: "customerDisplay", label: "display.open", icon: "grid" });

  rows.push({
    key: "closeDay",
    label: "shift.closeDay",
    icon: "calendar",
    // The date, because "end of day" is ambiguous at one in the morning.
    detail: shift.state?.day.opened_at ? dateOnly(shift.state.day.opened_at) : undefined,
    destructive: true,
  });

  // Last, and the only way out of the app now that the till screen is gone
  // (D-055). Signing out by accident mid-rush is confirmed first.
  rows.push({ key: "logout", label: "home.logout", icon: "logout", destructive: true });

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
    <div
      v-if="whereWeAre"
      class="border-b border-line bg-background px-4 py-2"
    >
      <p
        v-if="restaurant"
        class="truncate text-xs font-semibold"
      >
        {{ restaurant }}
      </p>
      <p class="truncate text-xs text-muted">
        {{ whereWeAre }}
      </p>
    </div>

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
