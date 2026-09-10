// @vitest-environment jsdom

/**
 * The order a shift runs in, as the screens read it (`D-177`, `FR-8.4`).
 *
 * Arrive, take the drawer, work, count it, go home. The welcome screen and the
 * till menu both draw their attendance button from `punchOnOffer`, so this is
 * the table both of them obey — and the table the server enforces again in
 * `attendance.punch`.
 *
 * The case that started it: the button was picked from `clockedIn` alone, so a
 * cashier holding an open drawer was offered the way home. A clock-out over an
 * open till leaves a count nobody made against somebody no longer at work.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { Identity } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";

function identity(over: { clocked_in?: boolean; holding_till?: boolean; employee?: string | null }) {
  return {
    user: "cashier@example.com",
    full_name: "Cashier",
    pos_profile: "T1",
    attendance: {
      employee: over.employee === undefined ? "HR-EMP-0001" : over.employee,
      clocked_in: over.clocked_in ?? false,
      since: over.clocked_in ? "2026-09-10 07:00:00" : null,
    },
    holding_till: over.holding_till ?? false,
    pin_length: 5,
  } as Identity;
}

function signedInAs(over: Parameters<typeof identity>[0]) {
  const auth = useAuthStore();
  auth.identity = identity(over);
  return auth;
}

beforeEach(() => setActivePinia(createPinia()));

describe("which attendance button is on offer", () => {
  it("offers a clock-in to somebody who has not arrived", () => {
    expect(signedInAs({ clocked_in: false }).punchOnOffer).toBe("in");
  });

  it("offers a clock-out once the drawer has been counted", () => {
    expect(signedInAs({ clocked_in: true, holding_till: false }).punchOnOffer).toBe("out");
  });

  it("offers nothing while the drawer is still open", () => {
    const auth = signedInAs({ clocked_in: true, holding_till: true });

    expect(auth.punchOnOffer).toBeNull();
    // And the screen is told why, rather than drawing nothing (`D-074`).
    expect(auth.heldByTill).toBe(true);
  });

  it("still offers a clock-in over an open drawer", () => {
    // Deliberately not symmetrical: somebody who took the drawer having
    // forgotten to clock in must still be able to record that they are here.
    expect(signedInAs({ clocked_in: false, holding_till: true }).punchOnOffer).toBe("in");
  });

  it("offers nothing to a login with no employee behind it", () => {
    // An administrator or an integration user is on no payroll, and a button
    // that always refuses is worse than no button.
    const auth = signedInAs({ employee: null });

    expect(auth.punchOnOffer).toBeNull();
    expect(auth.heldByTill).toBe(false);
  });

  it("offers nothing before anybody has signed in", () => {
    expect(useAuthStore().punchOnOffer).toBeNull();
  });
});
