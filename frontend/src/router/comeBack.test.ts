// @vitest-environment jsdom

/**
 * A full page load comes back to the screen it was on (`D-221`).
 *
 * Every load stops at setup to fetch the terminal, and setup used to end on
 * home whatever was asked for — so a refresh on a bill, or the reload after an
 * update when Pay was pressed, lost the screen. The guard now carries where it
 * was going.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/api/auth";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";

vi.mock("@/api/auth", () => ({ me: vi.fn(), signIn: vi.fn(), signOut: vi.fn() }));

beforeEach(async () => {
  setActivePinia(createPinia());
  await router.replace({ name: "sign-in" });

  const auth = useAuthStore();
  auth.known = true;
  auth.identity = {
    user: "cashier@example.com",
    full_name: "نورة القحطاني",
    pos_profile: "T1",
    attendance: { employee: null, clocked_in: false, since: null },
    holding_till: false,
    pin_length: 5,
  } as Identity;
  // No terminal loaded: this is the first navigation after a page load.
});

describe("a page load that has to fetch the terminal first", () => {
  it("remembers the screen it was going to", async () => {
    await router.push({ name: "payment", params: { orderName: "RO-1" } });

    expect(router.currentRoute.value.name).toBe("setup");
    expect(router.currentRoute.value.query.next).toBe("/payment/RO-1");
  });

  it("carries nothing when the screen was home", async () => {
    await router.push({ name: "home" });

    expect(router.currentRoute.value.name).toBe("setup");
    expect(router.currentRoute.value.query.next).toBeUndefined();
  });
});
