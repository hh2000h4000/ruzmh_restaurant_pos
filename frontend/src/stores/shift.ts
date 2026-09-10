import { defineStore } from "pinia";
import { computed, ref } from "vue";

import * as shiftApi from "@/api/shift";
import type { ShiftReport, ShiftState } from "@/api/shift";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";

/**
 * The day and the drawer, for whichever screen is asking (FR-8.1..8.3, D-047).
 *
 * A store rather than a composable: both screens show the same two facts at the
 * same time, and two copies polling independently would disagree the moment one
 * of them opened a till.
 *
 * Nothing here works out money. Expected, counted and variance are the server's
 * answers (`CLAUDE.md` §5.1); a drawer count the screen calculated itself could
 * differ from the one ERPNext files.
 */
export const useShiftStore = defineStore("shift", () => {
  const session = useSessionStore();
  const auth = useAuthStore();

  const state = ref<ShiftState | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);

  const dayOpen = computed(() => Boolean(state.value?.day.open));
  const tillOpen = computed(() => Boolean(state.value?.till.open));

  /** Who has the drawer, when it is not this cashier. */
  const tillHeldByOther = computed(
    () => tillOpen.value && state.value?.till.is_mine === false,
  );

  async function run<T>(action: () => Promise<T>): Promise<T | null> {
    if (busy.value) return null;

    busy.value = true;
    error.value = null;
    try {
      return await action();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    } finally {
      busy.value = false;
    }
  }

  async function refresh(): Promise<void> {
    const profile = session.profile?.name;
    if (!profile) return;

    const next = await run(() => shiftApi.getShiftState(profile));
    if (next) state.value = next;
  }

  async function openTill(openingFloats?: Record<string, number>): Promise<boolean> {
    const profile = session.profile?.name;
    if (!profile) return false;

    const done = await run(() =>
      shiftApi.openTill({ pos_profile: profile, opening_floats: openingFloats }),
    );
    if (!done) return false;

    // The session payload carries the shift the terminal sells under, and
    // BR-044 reads it — so it has to be re-read, not patched.
    await session.load(profile);
    await auth.probe(profile);
    await refresh();
    return true;
  }

  async function closeTill(
    counted?: Record<string, number>,
    varianceReason?: string | null,
  ): Promise<boolean> {
    const entry = state.value?.till.entry;
    if (!entry) return false;

    const done = await run(() =>
      shiftApi.closeTill({
        opening_entry: entry,
        counted,
        variance_reason: varianceReason ?? null,
      }),
    );
    if (!done) return false;

    // The session payload carries the shift the terminal sells under, and
    // BR-044 reads it on every screen — so closing a drawer has to re-read it
    // too. Without this the till was closed on the server while the browser
    // still believed a shift was open, and the item guard never fired.
    //
    // The identity too (`D-177`): it carries whether a drawer is still this
    // person's to count, and that is what decides whether they may clock out.
    // Closing the till is the moment the answer changes, so a screen holding
    // the old one would go on refusing the button it should now offer.
    await session.load(session.profile!.name);
    await auth.probe(session.profile!.name);
    await refresh();
    return true;
  }

  async function closeDay(force = false): Promise<boolean> {
    const shift = state.value?.day.shift;
    if (!shift) return false;

    const done = await run(() => shiftApi.closeDay({ shift, force: force ? 1 : 0 }));
    if (!done) return false;

    // Closing the day settles every till still open under it, this cashier's
    // included — so the identity changes here as well.
    await session.load(session.profile!.name);
    await auth.probe(session.profile!.name);
    await refresh();
    return true;
  }

  /** The count a close will be measured against — read fresh, never cached. */
  async function tillSummary(): Promise<ShiftReport | null> {
    const entry = state.value?.till.entry;
    if (!entry) return null;
    return run(() => shiftApi.getTillSummary(entry));
  }

  async function daySummary(): Promise<ShiftReport | null> {
    const shift = state.value?.day.shift;
    if (!shift) return null;
    return run(() => shiftApi.getDaySummary(shift));
  }

  return {
    state,
    busy,
    error,
    dayOpen,
    tillOpen,
    tillHeldByOther,
    refresh,
    openTill,
    closeTill,
    closeDay,
    tillSummary,
    daySummary,
  };
});
