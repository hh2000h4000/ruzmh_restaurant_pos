/**
 * `D-220` — news floats and fades; an error floats and waits.
 */
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NOTICE_MS, useNoticeStore } from "@/stores/notice";

beforeEach(() => {
  setActivePinia(createPinia());
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("a notice", () => {
  it("goes by itself after four seconds when it is news", () => {
    const notice = useNoticeStore();
    notice.info("Receipt 12 sent to the printer");

    vi.advanceTimersByTime(NOTICE_MS - 1);
    expect(notice.current?.text).toBe("Receipt 12 sent to the printer");

    vi.advanceTimersByTime(1);
    expect(notice.current).toBeNull();
  });

  it("stays when it is an error, until the cashier closes it", () => {
    // A cashier looks at the customer, not the corner of the till: an error that
    // fades is an error nobody read.
    const notice = useNoticeStore();
    notice.error("No printer is linked to this terminal");

    vi.advanceTimersByTime(NOTICE_MS * 10);
    expect(notice.current?.kind).toBe("error");

    notice.dismiss();
    expect(notice.current).toBeNull();
  });

  it("replaces the last one rather than stacking", () => {
    const notice = useNoticeStore();
    notice.info("first");
    notice.info("second");

    expect(notice.current?.text).toBe("second");
  });

  it("does not let an old timer take away a newer notice", () => {
    const notice = useNoticeStore();
    notice.info("first");
    vi.advanceTimersByTime(NOTICE_MS - 100);
    notice.info("second");

    vi.advanceTimersByTime(200);
    expect(notice.current?.text).toBe("second");
  });

  it("waits while a finger is on it, and counts down again when it lifts", () => {
    const notice = useNoticeStore();
    notice.info("Shift report sent to the printer");

    notice.hold();
    vi.advanceTimersByTime(NOTICE_MS * 3);
    expect(notice.current).not.toBeNull();

    notice.release();
    vi.advanceTimersByTime(NOTICE_MS);
    expect(notice.current).toBeNull();
  });
});
