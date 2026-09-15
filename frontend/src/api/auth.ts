import { command, resetCsrfToken } from "@/api/client";

/** What `api/auth.me` answers — who is at the till, and their working time. */
export interface Identity {
  user: string;
  full_name: string;
  pos_profile: string | null;
  attendance: {
    employee: string | null;
    employee_name?: string | null;
    clocked_in: boolean;
    since: string | null;
  };
  /**
   * A drawer still open under this person's name, on any terminal (`D-177`).
   *
   * Beside `attendance` rather than inside it, because it is not attendance: it
   * is the one till fact a person's working time depends on, and the module
   * that answers it says why (`utils/attendance.holds_a_drawer`).
   */
  holding_till: boolean;
  /**
   * **Which** drawer (`D-218`): the terminal it is open on, and since when. The
   * one keeping somebody at work may be at another branch, and "close your
   * till" at a terminal whose drawer is closed sends them nowhere.
   */
  held_till: { pos_profile: string; opened_at: string } | null;
  /** From the server, so the boxes on the pad match what it will accept. */
  pin_length: number;
}

/**
 * Sign in with a PIN.
 *
 * The only call in the app that works without a session — a locked till has
 * nobody signed in to authorise the unlocking (`D-094`).
 */
export async function signIn(pin: string, posProfile: string | null): Promise<Identity> {
  const identity = await command<Identity>("auth.sign_in", { pin, pos_profile: posProfile });

  // The session is a different one now, and a CSRF token minted for the old
  // one is refused (`D-102`). Dropped here rather than in the store, so every
  // caller of this function gets it and none has to remember.
  resetCsrfToken();

  return identity;
}

export async function signOut(): Promise<{ signed_out: boolean }> {
  const result = await command<{ signed_out: boolean }>("auth.sign_out");
  resetCsrfToken();
  return result;
}

export function me(posProfile: string | null): Promise<Identity> {
  return command<Identity>("auth.me", { pos_profile: posProfile });
}

export function clockIn(posProfile: string | null): Promise<Identity["attendance"]> {
  return command("auth.clock_in", { pos_profile: posProfile });
}

export function clockOut(posProfile: string | null): Promise<Identity["attendance"]> {
  return command("auth.clock_out", { pos_profile: posProfile });
}
