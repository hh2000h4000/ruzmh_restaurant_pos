import { describe, expect, it } from "vitest";

import { COMMIT_AT, nextOffset, OPEN_AT, outcomeFor, swipeSign } from "./swipe";

/**
 * The swipe is the one gesture in the app with no button to fall back on, and
 * its direction inverts with the language. Both mistakes look like "the row
 * does not move" on the machine that is not being tested.
 */
describe("which way the row travels", () => {
  it("moves right in Arabic, where the drawer is on the left", () => {
    expect(swipeSign("rtl")).toBe(1);
  });

  it("moves left in English", () => {
    expect(swipeSign("ltr")).toBe(-1);
  });

  it("treats an unset direction as English, the way a browser does", () => {
    expect(swipeSign("")).toBe(-1);
  });
});

describe("where the row lands", () => {
  it("follows a finger dragging it open, in Arabic", () => {
    expect(nextOffset(0, 60, 1)).toBe(60);
  });

  it("follows a finger dragging it open, in English", () => {
    expect(nextOffset(0, -60, -1)).toBe(-60);
  });

  it("refuses to travel the other way", () => {
    expect(nextOffset(0, -60, 1)).toBe(0);
    expect(nextOffset(0, 60, -1)).toBe(-0);
  });

  it("carries on from where an already-open drawer was left", () => {
    expect(nextOffset(OPEN_AT, 40, 1)).toBe(OPEN_AT + 40);
  });

  it("lets an open drawer be pushed back shut, and no further", () => {
    expect(nextOffset(OPEN_AT, -OPEN_AT, 1)).toBe(0);
    expect(nextOffset(OPEN_AT, -500, 1)).toBe(0);
  });
});

describe("what letting go means", () => {
  it("springs back when barely moved", () => {
    expect(outcomeFor(0)).toBe("closed");
    expect(outcomeFor(OPEN_AT - 1)).toBe("closed");
  });

  it("holds the drawer open past the first threshold", () => {
    expect(outcomeFor(OPEN_AT)).toBe("open");
    expect(outcomeFor(COMMIT_AT - 1)).toBe("open");
  });

  it("asks to remove the line on a full swipe", () => {
    expect(outcomeFor(COMMIT_AT)).toBe("remove");
    expect(outcomeFor(400)).toBe("remove");
  });

  it("never removes before it would open — the thresholds cannot cross", () => {
    expect(COMMIT_AT).toBeGreaterThan(OPEN_AT);
  });
});
