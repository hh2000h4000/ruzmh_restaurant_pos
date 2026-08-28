/**
 * The arithmetic behind swiping a bill line aside (06 Screen 3).
 *
 * Split out from the component because this is the part that is easy to get
 * wrong and impossible to eyeball: the direction flips with the writing
 * direction, the row must refuse to travel the other way, and two thresholds
 * decide between "opened a drawer" and "asked to remove the line". The
 * component keeps the pointer plumbing; this keeps the rules, and the rules are
 * tested.
 */

/** How far the row must travel before the drawer stays open. */
export const OPEN_AT = 88;

/** Past this, letting go acts instead of only opening the drawer. */
export const COMMIT_AT = 180;

/**
 * Which way the row travels.
 *
 * The drawer sits at the row's trailing edge — the left in Arabic, the right in
 * English — so the row slides the other way to uncover it. `translateX` is
 * physical, so this is a sign and not a logical property.
 */
export function swipeSign(dir: string): 1 | -1 {
  return dir === "rtl" ? 1 : -1;
}

/**
 * Where the row sits after the pointer moved `deltaX` physical pixels.
 *
 * Clamped at zero in the opening direction: dragging the row the *other* way
 * is how a vertical scroll gets misread as a swipe, and a row that follows it
 * would tear away from the list.
 */
export function nextOffset(startOffset: number, deltaX: number, sign: 1 | -1): number {
  const travelled = startOffset * sign + deltaX * sign;
  return Math.max(0, travelled) * sign;
}

export type SwipeOutcome = "closed" | "open" | "remove";

/** What letting go at this distance means. */
export function outcomeFor(revealed: number): SwipeOutcome {
  if (revealed >= COMMIT_AT) return "remove";
  if (revealed >= OPEN_AT) return "open";
  return "closed";
}
