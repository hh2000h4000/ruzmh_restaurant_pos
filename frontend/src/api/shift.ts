/**
 * The business day, and the tills inside it (07 §, FR-8.1..8.3, D-047).
 *
 * Two levels, and the screen shows both: a till session is one cashier and one
 * drawer, a business day is the branch. Closing one is not closing the other.
 *
 * Nothing here computes money. Expected, counted and variance all come from the
 * server (`CLAUDE.md` §5.1) — a drawer count the screen worked out itself could
 * disagree with the one ERPNext files.
 */
import { mutate, query } from "./client";

/** One payment method in a drawer count. */
export interface MethodLine {
  method: string;
  /** `till` is money to count; `credit` was never in the drawer (D-029). */
  kind: "till" | "credit";
  opening: number;
  sales: number;
  expected: number;
  /** `null` for credit: there is nothing to count. */
  counted?: number | null;
  variance?: number | null;
}

export interface ShiftReport {
  shift: string | null;
  branch: string | null;
  status: string | null;
  entry?: string;
  user?: string;
  opened_at?: string;
  orders: { total: number; closed: number; cancelled: number; still_open: number };
  /**
   * Whether these open bills actually stand between the day and its close.
   *
   * **The server's answer, not the screen's.** The branch decides it (`D-105`,
   * `D-156`) and the endpoint enforces it; a screen that worked the rule out
   * again would be the second copy — the one that disagrees with the refusal.
   * Absent means any open bill blocks, which is the stricter reading.
   *
   * The report carries the two settings behind it as well, and this type does
   * not: nothing on screen reads them, and a field nobody reads is one that
   * goes quietly wrong.
   */
  blocked_by_open_orders?: boolean;
  /**
   * Whether the pile this branch is carrying is worth mentioning (`D-158`).
   *
   * A warning, never a refusal: the day closes either way. Ending the business
   * day is an accounting act and a long list is a technical complaint, so one
   * does not stop the other.
   */
  carrying_too_many?: boolean;
  /**
   * How many people are still on the clock at this branch (`D-178`).
   *
   * Closing the day sends every one of them home, at the moment it is closed.
   * Said on the screen the manager presses the button on, rather than found
   * later in a payroll report — it is the same courtesy the open bills get.
   */
  on_duty?: number;
  by_order_type: { order_type: string; title_ar: string; count: number; sales: number }[];
  /**
   * What each person took and refunded (FR-8.3, `D-218`) — a shared drawer is
   * counted once for everybody on it, and this is where it is traced to a name.
   */
  by_cashier: { user: string; name: string; count: number; sales: number; returns: number }[];
  by_method: MethodLine[];
  voids: number;
  sales: number;
  discounts: number;
  till_expected: number;
  credit_total: number;
}

export interface Settlement {
  settlement_required: boolean;
  methods: MethodLine[];
  expected: number;
  counted: number;
  variance: number;
  credit_total: number;
}

export interface ShiftState {
  branch: string;
  /** `multi` gives each cashier a drawer; `single` shares one (BR-041). */
  shift_type: "single" | "multi";
  settlement_required: boolean;
  day: {
    open: boolean;
    shift?: string;
    title?: string;
    opened_by?: string;
    opened_by_name?: string | null;
    opened_at?: string;
    is_mine?: boolean;
  };
  till: {
    open: boolean;
    entry?: string;
    user?: string;
    user_name?: string | null;
    opened_at?: string;
    is_mine?: boolean;
  };
}

export function getShiftState(posProfile: string): Promise<ShiftState> {
  return query<ShiftState>("shift.get_state", { pos_profile: posProfile });
}

export function getTillSummary(openingEntry: string): Promise<ShiftReport> {
  return query<ShiftReport>("shift.get_till_summary", { opening_entry: openingEntry });
}

export function getDaySummary(shift: string): Promise<ShiftReport> {
  return query<ShiftReport>("shift.get_day_summary", { shift });
}

/**
 * Take the drawer. Opens the day too if nobody has — one button in the morning.
 *
 * Not deferrable: a shift is what makes the terminal allowed to sell (BR-044),
 * and a device that decided that for itself could take orders no server ever
 * agreed to.
 */
export function openTill(payload: {
  pos_profile: string;
  opening_floats?: Record<string, number>;
}): Promise<{ entry: string; shift: string; joined: boolean }> {
  return mutate("shift.open_till", payload);
}

export function closeTill(payload: {
  opening_entry: string;
  counted?: Record<string, number>;
  variance_reason?: string | null;
}): Promise<{ closing_entry: string; settlement: Settlement; report: ShiftReport }> {
  return mutate("shift.close_till", payload);
}

export function closeDay(payload: {
  shift: string;
  force?: number;
  /** The terminal it was closed from, for the audit rows the close writes. */
  pos_profile?: string;
}): Promise<{
  shift: string;
  report: ShiftReport;
  closed_tills: string[];
  /** Who the close sent home (`D-178`). */
  clocked_out?: { employee: string; employee_name: string; at: string }[];
}> {
  return mutate("shift.close_day", payload);
}
