// @vitest-environment jsdom

/**
 * The welcome screen, and which attendance button it draws (`D-177`).
 *
 * The rule itself lives in the auth store and has its own tests; this holds the
 * **wiring** — that the screen reads that rule rather than deciding for itself,
 * which is what it used to do. It is also the screen the user was looking at:
 * "المفترض إذا دخل المستخدم بداية اليوم وليس لديه مناوبة مفتوحة تظهر عنده
 * الشاشة بزر تسجيل حضور".
 */
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/api/auth";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import SignInView from "@/views/SignInView.vue";

vi.mock("vue-router", () => ({ useRouter: () => ({ push: vi.fn() }) }));

function welcome(over: { clocked_in?: boolean; holding_till?: boolean }) {
  const auth = useAuthStore();
  auth.known = true;
  auth.identity = {
    user: "cashier@example.com",
    full_name: "سعيد الغامدي",
    pos_profile: "T1",
    attendance: {
      employee: "HR-EMP-0001",
      clocked_in: over.clocked_in ?? false,
      since: over.clocked_in ? "2026-09-10 07:00:00" : null,
    },
    holding_till: over.holding_till ?? false,
    pin_length: 5,
  } as Identity;

  return mount(SignInView, {
    global: { stubs: { DigitPad: true, LocaleToggle: true } },
  });
}

beforeEach(() => setActivePinia(createPinia()));

describe("the welcome screen's attendance button", () => {
  it("asks somebody arriving to clock in", () => {
    const screen = welcome({ clocked_in: false });

    expect(screen.text()).toContain(t("auth.clockIn"));
    expect(screen.text()).not.toContain(t("auth.clockOut"));
  });

  it("offers a clock-out once the drawer is counted", () => {
    const screen = welcome({ clocked_in: true, holding_till: false });

    expect(screen.text()).toContain(t("auth.clockOut"));
  });

  it("withholds the clock-out while the drawer is open, and says why", () => {
    const screen = welcome({ clocked_in: true, holding_till: true });

    expect(screen.text()).not.toContain(t("auth.clockOut"));
    expect(screen.text()).toContain(t("auth.closeTillFirst"));
  });

  it("still lets them into the till while the drawer is open", () => {
    // Withholding the punch must not withhold the work: the drawer they are
    // holding is open on this very terminal.
    expect(welcome({ clocked_in: true, holding_till: true }).text()).toContain(t("auth.enterTill"));
  });
});
