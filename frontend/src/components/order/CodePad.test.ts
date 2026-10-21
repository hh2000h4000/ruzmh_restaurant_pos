// @vitest-environment jsdom

/**
 * The letter pad, only where there is no other keyboard (`D-277`).
 *
 * Measured on a phone it was a second keyboard under the phone's own, 27 pixels
 * a key. The Windows till in kiosk mode raises none, so there it stays.
 */
import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import CodePad from "@/components/order/CodePad.vue";

function pad() {
  return mount(CodePad, { props: { value: "" } });
}

function device(agent: string, touchPoints = 0) {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(agent);
  // jsdom has no `maxTouchPoints` to spy on, so it is given one.
  Object.defineProperty(navigator, "maxTouchPoints", { value: touchPoints, configurable: true });
}

afterEach(() => {
  vi.restoreAllMocks();
  delete (navigator as { maxTouchPoints?: number }).maxTouchPoints;
});

describe("the letter pad", () => {
  it("is drawn on the Windows till, which raises no keyboard in kiosk mode", () => {
    device("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0", 10);

    expect(pad().findAll("button")).toHaveLength(38);
  });

  it("is not drawn on an Android phone or tablet", () => {
    device("Mozilla/5.0 (Linux; Android 14; SM-X710) Chrome/129.0", 5);

    expect(pad().findAll("button")).toHaveLength(0);
  });

  it("is not drawn on an iPad, which introduces itself as a Mac", () => {
    device("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", 5);

    expect(pad().findAll("button")).toHaveLength(0);
  });

  it("is drawn on a Mac, which has a keyboard but no touch", () => {
    // A Mac at a counter is a desk machine; the pad costs nothing there and is
    // what the guide shows.
    device("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", 0);

    expect(pad().findAll("button")).toHaveLength(38);
  });

  it("lays its keys out as a keyboard: digits, then Q, A and Z rows", () => {
    // `D-382` — the order a cashier's thumb knows from the phone, not A to Z.
    device("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0", 10);

    const keys = pad()
      .findAll("button")
      .map((button) => button.text().trim())
      .join("");
    expect(keys.startsWith("1234567890QWERTYUIOPASDFGHJKLZXCVBNMc")).toBe(true);
  });
});
