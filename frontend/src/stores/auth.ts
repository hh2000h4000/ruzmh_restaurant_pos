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
/**
 * Who typed their PIN on this till (`D-343`).
 *
 * **A login in the office is not a sign-in at the till.** The two share one
 * cookie, so a manager who opened the till from the desk was taken for the
 * cashier: no PIN pad, their name on the welcome screen, and — on a login that
 * was never set up to sell — a till that then refused everything, with nothing
 * saying that the person had simply never signed in here.
 *
 * So the till remembers who signed in *on it*, and believes the server's "you
 * are X" only when X is that person. It is kept in `localStorage` beside the
 * pairing, for the pairing's reason: a reload must not ask a cashier for their
 * PIN again mid-service.
 */
const TILL_USER = "rpos.till_user";

function signedInHere(): string | null {
  try {
    return localStorage.getItem(TILL_USER);
  } catch {
    return null;
  }
}

function rememberSignIn(user: string | null): void {
  try {
    if (user) localStorage.setItem(TILL_USER, user);
    else localStorage.removeItem(TILL_USER);
  } catch {
    // Storage refused: the next reload asks for the PIN again, which is the safe side.
  }
}

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

  /**
   * Which attendance button this person should be offered (`D-177`, `FR-8.4`).
   *
   * **The order of a shift, in one expression** — arrive, open the drawer, work,
   * close the drawer, go home. Read by the welcome screen and by the till menu,
   * because two screens asking one question have to agree (`CLAUDE.md` §5.5);
   * the till menu once decided this for itself and offered a clock-out to a
   * cashier holding an open drawer.
   *
   * `null` while the drawer is open: there is nothing to offer yet, and the
   * screen says so in words rather than drawing nothing (`D-074`).
   *
   * Clocking **in** is never withheld. Somebody who opened a drawer having
   * forgotten to clock in must still be able to record that they are here.
   */
  const punchOnOffer = computed<"in" | "out" | null>(() => {
    if (!isEmployee.value) return null;
    if (!clockedIn.value) return "in";
    return identity.value?.holding_till ? null : "out";
  });

  /** Why no clock-out is offered, when that is the reason. */
  const heldByTill = computed(() => clockedIn.value && identity.value?.holding_till === true);

  /**
   * This login is on no payroll, so attendance is not its to record (`D-184`).
   *
   * **A refusal the reader can lift**, which is the distinction `D-139` missed.
   * That decision hid the entry entirely on the rule that a button which always
   * refuses is worse than no button — right for a permanent condition, and this
   * is not one: linking the login to an `Employee` fixes it, and the person who
   * can do that is the one signing in. Hidden, they had nothing to act on and
   * nothing to search for, which is how the user met it.
   *
   * The same shape `FR-2.1b` already uses for order types that cannot be
   * converted: listed disabled with the reason, not hidden.
   */
  const notOnPayroll = computed(() => signedIn.value && !isEmployee.value);

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
      // `D-343` — and only the person who signed in at this till.
      identity.value = found.user !== "Guest" && found.user === signedInHere() ? found : null;
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
    rememberSignIn(found.user);
    return true;
  }

  async function signOut(): Promise<void> {
    await run(() => api.signOut());
    // Cleared whatever the server said. A sign-out that leaves somebody's name
    // on the screen because the request failed is worse than one that forgets
    // too eagerly: the next person would be looking at the last one's till.
    identity.value = null;
    known.value = true;
    rememberSignIn(null);
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
    rememberSignIn(null);
  }

  /**
   * Clock in or out — whichever is on offer, and nothing when none is.
   *
   * The direction comes from `punchOnOffer` rather than from `clockedIn`, so
   * the button and the request cannot disagree: read the other way, a stale
   * screen would send a clock-out the server is bound to refuse.
   */
  async function punch(posProfile: string | null): Promise<void> {
    const direction = punchOnOffer.value;
    if (!direction) return;

    const going = direction === "in" ? api.clockIn : api.clockOut;
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
    punchOnOffer,
    heldByTill,
    notOnPayroll,
    probe,
    signIn,
    signOut,
    forget,
    punch,
  };
});
