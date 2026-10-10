// @vitest-environment jsdom

/**
 * A login in the office is not a sign-in at the till (`D-343`).
 *
 * The desk and the till share one cookie, so the server's "you are X" is true
 * of a manager who only opened the till from the workspace. The till believes
 * it only of the person who typed their PIN here.
 */
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api/auth";
import type { Identity } from "@/api/auth";
import { useAuthStore } from "@/stores/auth";

vi.mock("@/api/auth", () => ({
  me: vi.fn(),
  signIn: vi.fn(),
  signOut: vi.fn(),
  clockIn: vi.fn(),
  clockOut: vi.fn(),
}));

function who(user: string): Identity {
  return {
    user,
    full_name: user,
    pos_profile: "T1",
    attendance: { employee: "HR-EMP-0001", clocked_in: false, since: null },
    holding_till: false,
    pin_length: 5,
  } as Identity;
}

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
  vi.clearAllMocks();
});

describe("who the till takes to be standing at it", () => {
  it("does not take a desk login for a sign-in: the PIN pad is shown", async () => {
    vi.mocked(api.me).mockResolvedValue(who("manager@example.com"));
    const auth = useAuthStore();

    await auth.probe("T1");

    expect(auth.signedIn).toBe(false);
    expect(auth.known).toBe(true);
  });

  it("keeps the cashier who typed their PIN here, across a reload", async () => {
    vi.mocked(api.signIn).mockResolvedValue(who("cashier@example.com"));
    await useAuthStore().signIn("12345", "T1");

    // A reload: a new store, the same browser.
    setActivePinia(createPinia());
    vi.mocked(api.me).mockResolvedValue(who("cashier@example.com"));
    const auth = useAuthStore();
    await auth.probe("T1");

    expect(auth.signedIn).toBe(true);
  });

  it("asks again once the cookie has become somebody else's", async () => {
    vi.mocked(api.signIn).mockResolvedValue(who("cashier@example.com"));
    await useAuthStore().signIn("12345", "T1");

    setActivePinia(createPinia());
    vi.mocked(api.me).mockResolvedValue(who("manager@example.com"));
    const auth = useAuthStore();
    await auth.probe("T1");

    expect(auth.signedIn).toBe(false);
  });

  it("forgets on the way out, so the next reload asks for a PIN", async () => {
    vi.mocked(api.signIn).mockResolvedValue(who("cashier@example.com"));
    vi.mocked(api.signOut).mockResolvedValue({ signed_out: true } as never);
    const first = useAuthStore();
    await first.signIn("12345", "T1");
    await first.signOut();

    setActivePinia(createPinia());
    vi.mocked(api.me).mockResolvedValue(who("cashier@example.com"));
    const auth = useAuthStore();
    await auth.probe("T1");

    expect(auth.signedIn).toBe(false);
  });
});
