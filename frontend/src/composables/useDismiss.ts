import { onMounted, onUnmounted, ref, type Ref } from "vue";

/**
 * A menu closes when the cashier looks elsewhere.
 *
 * **The bug this exists for.** Four popovers in this app opened on a tap and
 * then stayed — a tap anywhere else on the screen did nothing, and the only way
 * out was to find the same small button again or pick an entry the cashier did
 * not want. On a till that is worse than it sounds: the sheet covers the item
 * grid, so the next dish is tapped *through* nothing and the cashier is left
 * hunting for the way back while a queue waits.
 *
 * **One place, not four.** Every one of them asked the same question — "is this
 * tap still about the menu?" — and a rule remembered in four components is a
 * rule forgotten in one of them (§5.5). The fifth popover somebody adds gets it
 * by calling this.
 *
 * ## Why `click` and not `pointerdown`
 *
 * `pointerdown` fires before the browser knows a finger is scrolling rather
 * than tapping — the reason `main.css` refuses to act on it. A menu dismissed
 * by the *start* of a scroll over the list behind it would vanish mid-gesture,
 * and the cashier would not know why. `click` fires once the gesture resolves.
 *
 * ## Why the whole anchor, and not just the panel
 *
 * The listener sits on `document` for the life of the component, and the tap
 * that *opens* the menu bubbles up to it like any other. If the trigger counted
 * as outside, that same tap would close what it just opened and the menu would
 * never appear at all. So the anchor is the element holding **both the trigger
 * and the panel**, and the open tap lands inside it.
 *
 * A tap outside closes the menu and still reaches whatever it landed on. That
 * is deliberate: swallowing the first tap to dismiss makes the cashier press
 * "send to kitchen" twice, and a till that ignores a press is a till nobody
 * trusts.
 *
 * Escape closes too, for the same reason `BaseDialog` honours it.
 *
 * @param open The popover's own flag. Set to `false` here, never to `true`.
 * @returns The ref to put on the element wrapping the trigger and the panel.
 */
export function useDismiss(open: Ref<boolean>): Ref<HTMLElement | null> {
  const anchor = ref<HTMLElement | null>(null);

  function onClick(event: MouseEvent): void {
    if (!open.value) return;

    const target = event.target as Node | null;
    if (target && anchor.value?.contains(target)) return;

    open.value = false;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (open.value && event.key === "Escape") open.value = false;
  }

  onMounted(() => {
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeydown);
  });

  onUnmounted(() => {
    document.removeEventListener("click", onClick);
    document.removeEventListener("keydown", onKeydown);
  });

  return anchor;
}
