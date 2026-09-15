// @vitest-environment jsdom

/**
 * The welcome screen: which attendance button it draws, and where the punch
 * leads (`D-177`, `D-179`).
 *
 * Two defects the user found on this screen, in that order. First it offered a
 * clock-out over an open drawer. Then, once the button was right, it recorded
 * the punch and **stayed** — so `punchOnOffer` flipped and drew the opposite
 * action under the finger that had just tapped: *"نقرت عليها وظهر شاشة تسجيل
 * انصراف ونقرت عليها"*, clocked in and back out in two taps without ever
 * opening a shift.
 *
 * `FR-8.4` step 3 had said since Phase 4 that clocking in drops the cashier
 * into the till screen. It was never wired. These hold both halves: the button
 * that is drawn, and the place the tap leads.
 */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Identity } from "@/api/auth";
import { sinceWhen, t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import SignInView from "@/views/SignInView.vue";

const api = vi.hoisted(() => ({
  push: vi.fn(),
  clockIn: vi.fn(),
  clockOut: vi.fn(),
  signOut: vi.fn(),
  signIn: vi.fn(),
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: api.push }) }));
vi.mock("@/api/auth", () => ({
  clockIn: api.clockIn,
  clockOut: api.clockOut,
  signOut: api.signOut,
  me: vi.fn(),
  signIn: api.signIn,
}));

function identity(over: {
  clocked_in?: boolean;
  holding_till?: boolean;
  employee?: string | null;
}): Identity {
  return {
    user: "cashier@example.com",
    full_name: "سعيد الغامدي",
    pos_profile: "T1",
    attendance: {
      employee: over.employee === undefined ? "HR-EMP-0001" : over.employee,
      clocked_in: over.clocked_in ?? false,
      since: over.clocked_in ? "2026-09-10 07:00:00" : null,
    },
    holding_till: over.holding_till ?? false,
    held_till: over.holding_till ? { pos_profile: "Riyadh Main Terminal", opened_at: "2026-09-14 10:57:00" } : null,
    pin_length: 5,
  } as Identity;
}

function welcome(over: Parameters<typeof identity>[0]) {
  const auth = useAuthStore();
  auth.known = true;
  auth.identity = identity(over);

  return mount(SignInView, {
    global: { stubs: { DigitPad: true, LocaleToggle: true } },
  });
}

/** The attendance button, whichever way it reads. */
function punchButton(screen: ReturnType<typeof welcome>) {
  return screen
    .findAll("button")
    .find((button) => [t("auth.clockIn"), t("auth.clockOut")].includes(button.text()));
}

beforeEach(() => {
  setActivePinia(createPinia());
  api.push.mockReset();
  api.clockIn.mockReset();
  api.clockOut.mockReset();
  api.signOut.mockReset();
  api.signIn.mockReset();
});

/**
 * `D-207` — the pad drew a fixed "wrong PIN" whatever the server answered.
 *
 * The user typed six wrong PINs: the device was locked (`D-204`), and the screen
 * went on saying the PIN was wrong, so the one person who could wait five minutes
 * kept typing instead.
 */
describe("the PIN pad", () => {
  async function typeAPin(message: string) {
    api.signIn.mockRejectedValue(new Error(message));
    const auth = useAuthStore();
    auth.known = true;
    auth.identity = null;

    const screen = mount(SignInView, {
      global: { stubs: { DigitPad: true, LocaleToggle: true } },
    });
    screen.findComponent({ name: "DigitPad" }).vm.$emit("update", "9".repeat(auth.pinLength));
    await flushPromises();

    return screen;
  }

  it("says the device has to wait when the server says so", async () => {
    const lock = "Too many wrong PINs on this device. Try again in 5 minutes.";

    expect((await typeAPin(lock)).text()).toContain(lock);
  });

  it("says a wrong PIN in the server's own words", async () => {
    const wrong = "That PIN was not recognised.";

    expect((await typeAPin(wrong)).text()).toContain(wrong);
  });
});

describe("the welcome screen's attendance button", () => {
  it("asks somebody arriving to clock in", () => {
    const screen = welcome({ clocked_in: false });

    expect(screen.text()).toContain(t("auth.clockIn"));
    expect(screen.text()).not.toContain(t("auth.clockOut"));
  });

  it("offers a clock-out once the drawer is counted", () => {
    expect(welcome({ clocked_in: true, holding_till: false }).text()).toContain(t("auth.clockOut"));
  });

  it("withholds the clock-out while the drawer is open, and says why", () => {
    const screen = welcome({ clocked_in: true, holding_till: true });

    expect(screen.text()).not.toContain(t("auth.clockOut"));
    // Naming the drawer (`D-218`): the user stood at a terminal whose drawer was
    // closed, theirs was open at another branch, and "close your till" sent them
    // nowhere.
    expect(screen.text()).toContain(
      t("auth.closeTillOn", {
        terminal: "Riyadh Main Terminal",
        since: sinceWhen("2026-09-14 10:57:00"),
      }),
    );
  });

  it("still lets them into the till while the drawer is open", () => {
    // Withholding the punch must not withhold the work: the drawer they are
    // holding is open on this very terminal.
    expect(welcome({ clocked_in: true, holding_till: true }).text()).toContain(t("auth.enterTill"));
  });
});

/**
 * Arrive before you sell (`D-186`).
 *
 * The user found the hole: *"ممكن يسوي دخول للكاشير ويبيع حتى لو ما سجل حضور"*.
 * The way into the till sat beside the clock-in as an equal choice, so a cashier
 * could walk past it and work all evening with no record of having been there —
 * and the shift they were owed for existed nowhere.
 *
 * The rule is narrow on purpose: it stops **only** somebody who owes an arrival.
 * Everyone else keeps the button, because for them there is nothing else to do
 * on this screen.
 */
describe("the way into the till", () => {
  it("is not offered while an arrival is owed", () => {
    expect(welcome({ clocked_in: false }).text()).not.toContain(t("auth.enterTill"));
  });

  it("is the clock-in that carries them in, and it is the filled button", () => {
    // At most one button wears the brand colour: the one that moves them on.
    const screen = welcome({ clocked_in: false });

    expect(punchButton(screen)!.classes()).toContain("bg-primary");
  });

  it("is offered to somebody already at work", () => {
    expect(welcome({ clocked_in: true, holding_till: false }).text()).toContain(
      t("auth.enterTill"),
    );
  });

  it("is offered to a login on no payroll", () => {
    // They can never clock in, so withholding it would lock them out entirely.
    expect(welcome({ employee: null }).text()).toContain(t("auth.enterTill"));
  });
});

describe("a login on no payroll", () => {
  /**
   * `D-184` — the attendance button used to vanish, and the screen was skipped
   * outright, so the owner signing in found no button anywhere and nothing
   * anywhere saying why. `D-139` was right that a control which always refuses
   * is worse than none — and wrong that this is one of those: linking the login
   * to an `Employee` lifts it, and the person who can do that is the one
   * standing here.
   */
  it("draws the clock-in disabled rather than hiding it", () => {
    const screen = welcome({ employee: null });
    const button = punchButton(screen);

    expect(button).toBeTruthy();
    expect(button!.attributes("disabled")).toBeDefined();
  });

  it("says what has to happen for it to work", () => {
    expect(welcome({ employee: null }).text()).toContain(t("auth.noEmployeeRecord"));
  });

  it("does not punch when the disabled button is driven anyway", async () => {
    // The screen's own guard is cosmetic; the store refuses on the same fact.
    const screen = welcome({ employee: null });

    await punchButton(screen)!.trigger("click");
    await flushPromises();

    expect(api.clockIn).not.toHaveBeenCalled();
  });

  it("still lets them into the till", () => {
    // They are here to work, not to be paid by the hour.
    expect(welcome({ employee: null }).text()).toContain(t("auth.enterTill"));
  });
});

describe("where the punch leads", () => {
  it("clocking in takes the cashier to the till", async () => {
    api.clockIn.mockResolvedValue({
      employee: "HR-EMP-0001",
      clocked_in: true,
      since: "2026-09-10 08:00:00",
    });
    const screen = welcome({ clocked_in: false });

    await punchButton(screen)!.trigger("click");
    await flushPromises();

    expect(api.clockIn).toHaveBeenCalledOnce();
    expect(api.push).toHaveBeenCalledOnce();
  });

  it("never leaves the opposite action under the finger that just tapped", async () => {
    // The defect as reported: clock in, and a clock-out button appears exactly
    // where the clock-in was.
    api.clockIn.mockResolvedValue({
      employee: "HR-EMP-0001",
      clocked_in: true,
      since: "2026-09-10 08:00:00",
    });
    const screen = welcome({ clocked_in: false });

    await punchButton(screen)!.trigger("click");
    await flushPromises();

    expect(api.clockOut).not.toHaveBeenCalled();
    expect(api.push).toHaveBeenCalledOnce();
  });

  it("clocking out signs them out of the terminal", async () => {
    api.clockOut.mockResolvedValue({ employee: "HR-EMP-0001", clocked_in: false, since: null });
    const screen = welcome({ clocked_in: true, holding_till: false });

    await punchButton(screen)!.trigger("click");
    await flushPromises();

    expect(api.clockOut).toHaveBeenCalledOnce();
    expect(api.signOut).toHaveBeenCalledOnce();
  });

  it("stays put when the punch was refused", async () => {
    // The server is the authority and it said no; moving on would hide that.
    api.clockIn.mockRejectedValue(new Error("You are already clocked in."));
    const screen = welcome({ clocked_in: false });

    await punchButton(screen)!.trigger("click");
    await flushPromises();

    expect(api.push).not.toHaveBeenCalled();
    expect(api.signOut).not.toHaveBeenCalled();
    expect(screen.text()).toContain("You are already clocked in.");
  });
});
