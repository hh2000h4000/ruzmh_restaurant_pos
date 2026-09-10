// @vitest-environment jsdom

/**
 * Arrive before you sell (`D-186`).
 *
 * The welcome screen stops offering the way into the till while a clock-in is
 * owed — and a screen is not where a rule like this can rest. A bookmark, the
 * back button, or a URL typed on a keyboard the kiosk normally has not got all
 * walk around it. The guard holds the same line one layer down, and this drives
 * the real router to prove it.
 *
 * **It is deliberately narrow.** Only a punch genuinely on offer stops anybody.
 * A login on no payroll can never clock in and would otherwise be locked out of
 * the app entirely; somebody already at work has nothing to punch; one holding a
 * drawer is refused the clock-out anyway (`D-177`). All three go straight
 * through, and each has its own test here because each is a different way the
 * rule could be written too widely.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/api/auth";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";
import type { PosSession } from "@/types/session";

vi.mock("@/api/auth", () => ({ me: vi.fn(), signIn: vi.fn(), signOut: vi.fn() }));

/** Sign somebody in, ask for the till, and report where they ended up. */
async function asksForTheTill(over: {
  clocked_in?: boolean;
  holding_till?: boolean;
  employee?: string | null;
}): Promise<string> {
  const auth = useAuthStore();
  auth.known = true;
  auth.identity = {
    user: "cashier@example.com",
    full_name: "نورة القحطاني",
    pos_profile: "T1",
    attendance: {
      employee: over.employee === undefined ? "HR-EMP-0001" : over.employee,
      clocked_in: over.clocked_in ?? false,
      since: over.clocked_in ? "2026-09-10 07:00:00" : null,
    },
    holding_till: over.holding_till ?? false,
    pin_length: 5,
  } as Identity;

  // The terminal is set up; without it the guard sends everyone to `setup` and
  // this file would be testing that instead.
  useSessionStore().data = { pos_profile: { name: "T1" } } as unknown as PosSession;

  await router.push({ name: "home" });
  await router.isReady();

  return String(router.currentRoute.value.name);
}

beforeEach(async () => {
  setActivePinia(createPinia());
  await router.replace({ name: "sign-in" });
});

describe("who the till lets in", () => {
  it("turns back somebody who has not clocked in", async () => {
    expect(await asksForTheTill({ clocked_in: false })).toBe("sign-in");
  });

  it("lets in somebody already at work", async () => {
    expect(await asksForTheTill({ clocked_in: true })).toBe("home");
  });

  it("lets in somebody holding a drawer", async () => {
    // They are mid-shift by definition, and the clock-out is withheld from them
    // until they count it (`D-177`).
    expect(await asksForTheTill({ clocked_in: true, holding_till: true })).toBe("home");
  });

  it("lets in a login on no payroll", async () => {
    // It can never clock in, so a wider rule would lock the owner out of their
    // own till.
    expect(await asksForTheTill({ employee: null })).toBe("home");
  });
});
