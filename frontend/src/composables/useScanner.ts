import { onMounted, onUnmounted } from "vue";

/**
 * A barcode reader, heard wherever the cashier's finger is not typing (`D-341`).
 *
 * **A reader is a keyboard.** It types the digits and presses Enter, and nothing
 * in the browser says the keys came from a gun rather than a hand. Two things
 * tell them apart well enough: the keys arrive a few milliseconds apart, and
 * nobody is in a text field.
 *
 * - **Not while a field has the focus.** There the keys are the field's, and the
 *   search box reads a scanned code itself on Enter.
 * - **Not while a dialog is open.** A scan behind the coupon sheet would put an
 *   item on a bill the cashier is not looking at.
 * - **Not slow typing.** A gap longer than `GAP_MS` starts again, so a stray key
 *   followed by Enter a second later is not a barcode.
 *
 * No timer runs and nothing is asked of the server: the listener is idle until
 * a key is pressed.
 */
const GAP_MS = 100;
const SHORTEST = 4;

export function useScanner(onScan: (code: string) => void): void {
  let buffer = "";
  let last = 0;

  function onKeydown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null;
    if (target?.closest?.("input, textarea, select, [contenteditable]")) return;
    if (document.querySelector('[role="dialog"]')) return;

    const now = Date.now();
    if (now - last > GAP_MS) buffer = "";
    last = now;

    if (event.key === "Enter") {
      const code = buffer;
      buffer = "";
      if (code.length >= SHORTEST) onScan(code);
      return;
    }

    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) buffer += event.key;
  }

  onMounted(() => document.addEventListener("keydown", onKeydown));
  onUnmounted(() => document.removeEventListener("keydown", onKeydown));
}
