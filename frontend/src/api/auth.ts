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
