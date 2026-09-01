import { defineStore } from "pinia";
import { computed, ref } from "vue";

import * as api from "@/api/auth";
import type { Identity } from "@/api/auth";

/**
 * Who is at the till.
 *
 * **Separate from the session store on purpose.** That one answers "which
 * terminal is this, and what may it sell" — a property of the machine, cached
 * on the device and unchanged all day. This answers "who is standing here",
 * which changes at every handover. Two different questions (`CLAUDE.md` §5.5),
 * and folding them together would mean re-loading a menu every time somebody
 * clocked in.
 */
export const useAuthStore = defineStore("auth", () => {
  const identity = ref<Identity | null>(null);
  const busy = ref(false);
  const error = ref<string | null>(null);
  /** Null until the first probe answers — "unknown" is not "signed out". */
  const known = ref(false);

  const signedIn = computed(() => identity.value !== null);
  const fullName = computed(() => identity.value?.full_name ?? "");
  const attendance = computed(() => identity.value?.attendance ?? null);
  const isEmployee = computed(() => Boolean(identity.value?.attendance.employee));
  const clockedIn = computed(() => identity.value?.attendance.clocked_in === true);
  const pinLength = computed(() => identity.value?.pin_length ?? 5);

  async function run<T>(work: () => Promise<T>): Promise<T | null> {
    busy.value = true;
    error.value = null;
    try {
      return await work();
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    } finally {
      busy.value = false;
    }
  }

  /**
   * Ask the server who we are, once, on start-up.
   *
   * A failure here is the ordinary case — a terminal nobody has signed into
   * yet — so it clears the identity rather than surfacing an error. `known`
   * is what the router waits for.
   */
  async function probe(posProfile: string | null): Promise<void> {
    try {
      const found = await api.me(posProfile);
      identity.value = found.user === "Guest" ? null : found;
    } catch {
      identity.value = null;
    } finally {
      known.value = true;
    }
  }

  async function signIn(pin: string, posProfile: string | null): Promise<boolean> {
    const found = await run(() => api.signIn(pin, posProfile));
    if (!found) return false;

    identity.value = found;
    known.value = true;
    return true;
  }

  async function signOut(): Promise<void> {
    await run(() => api.signOut());
    // Cleared whatever the server said. A sign-out that leaves somebody's name
    // on the screen because the request failed is worse than one that forgets
    // too eagerly: the next person would be looking at the last one's till.
    identity.value = null;
    known.value = true;
  }

  /**
   * Drop the identity without asking the server (`D-101`).
   *
   * For when the server has already decided: a request came back
   * unauthenticated, so there is no session left to call `sign_out` on, and
   * trying would be one more failing request in front of a cashier who needs
   * the keypad.
   */
  function forget(): void {
    identity.value = null;
    known.value = true;
  }

  async function punch(posProfile: string | null): Promise<void> {
    const going = clockedIn.value ? api.clockOut : api.clockIn;
    const state = await run(() => going(posProfile));
    if (state && identity.value) identity.value = { ...identity.value, attendance: state };
  }

  return {
    identity,
    busy,
    error,
    known,
    signedIn,
    fullName,
    attendance,
    isEmployee,
    clockedIn,
    pinLength,
    probe,
    signIn,
    signOut,
    forget,
    punch,
  };
});
