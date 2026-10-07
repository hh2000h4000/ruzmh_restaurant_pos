import { defineStore } from "pinia";
import { ref } from "vue";

/**
 * News about something the cashier just did, floating over the screen (`D-220`).
 *
 * **Why not a line in the page.** The notice used to sit above the menu grid and
 * push it down: on a small screen a row of dishes left the view every time a
 * receipt was printed. A notice is news about one action, not a state of the
 * till, so it floats and moves nothing — Material's snackbar, Carbon's toast.
 *
 * **An error goes too, and takes twice as long** (`D-331`). It used not to fade
 * at all — Nielsen Norman Group watched somebody wait five minutes on a screen
 * whose error had gone after five seconds. But a till's refusals are mostly
 * small and immediate ("Miranda is sold out"), the cashier has just tapped the
 * thing it is about, and one that waited to be closed sat over the menu through
 * the next three orders: the owner asked for it to show and go. It stays for
 * `ERROR_MS`, pauses under a finger like news does, and closes on a tap.
 *
 * **One at a time.** The newest replaces the last rather than stacking — a pile
 * of old news over the dishes is the problem this exists to remove.
 *
 * States of the till and the bill — a bill kept on this device, a ticket that did
 * not print — are not notices. They stay beside what they are about.
 */

/** How long news stays up before it goes by itself — the user's choice. */
export const NOTICE_MS = 4000;

/** A refusal is read, not glanced at: twice as long as news. */
export const ERROR_MS = 8000;

export type NoticeKind = "info" | "error";

export interface Notice {
  /** New for every notice, so the same sentence twice still reads as news. */
  id: number;
  kind: NoticeKind;
  text: string;
}

export const useNoticeStore = defineStore("notice", () => {
  const current = ref<Notice | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let issued = 0;

  function stopTimer(): void {
    if (timer) clearTimeout(timer);
    timer = null;
  }

  /** Both count down; a refusal for longer. */
  function startTimer(): void {
    stopTimer();
    if (current.value) timer = setTimeout(dismiss, current.value.kind === "info" ? NOTICE_MS : ERROR_MS);
  }

  function show(kind: NoticeKind, text: string): void {
    issued += 1;
    current.value = { id: issued, kind, text };
    startTimer();
  }

  function info(text: string): void {
    show("info", text);
  }

  function error(text: string): void {
    show("error", text);
  }

  function dismiss(): void {
    stopTimer();
    current.value = null;
  }

  /**
   * A finger or a pointer on the notice holds it (WCAG 2.2.1): somebody reading
   * it slowly is not raced by the timer.
   */
  function hold(): void {
    stopTimer();
  }

  function release(): void {
    startTimer();
  }

  return { current, info, error, dismiss, hold, release };
});
