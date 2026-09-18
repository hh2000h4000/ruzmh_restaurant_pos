// @vitest-environment jsdom

/**
 * Pair before you sign in (`D-226`).
 *
 * A freshly installed till knows nothing: not the branch, not the menu, not who
 * may work there. The PIN pad is scoped to a terminal, so it cannot be the first
 * screen — and the guard used to make it one, sending a machine that had never
 * been paired to a screen it had no way to answer. The user met exactly that on
 * their own till: a refresh, and a sign-in screen where the pairing box belonged.
 *
 * This drives the real router, because the rule lives in the guard rather than
 * in any screen.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import router from "@/router";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";

vi.mock("@/api/auth", () => ({ me: vi.fn(), signIn: vi.fn(), signOut: vi.fn() }));

describe("a till nobody has paired yet", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    const auth = useAuthStore();
    auth.known = true;
    auth.identity = null;
    useSessionStore().data = null;
  });

  it("is asked for a pairing code, not for a PIN", async () => {
    // The till, as a cashier finds it: the app opens on the floor, and the
    // guard decides what it is allowed to show.
    await router.push({ name: "home" });
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("setup");
  });

  it("is still asked for one when it lands deeper in the app", async () => {
    await router.push("/order/RO-2026-09-00001");
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("setup");
    expect(router.currentRoute.value.query.next).toBe("/order/RO-2026-09-00001");
  });

  it("still asks for a PIN once it knows which terminal it is", async () => {
    useSessionStore().data = { pos_profile: { name: "T1" } } as never;

    await router.push({ name: "home" });
    await router.isReady();

    expect(router.currentRoute.value.name).toBe("sign-in");
  });
});
