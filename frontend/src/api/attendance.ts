/**
 * Who is at work, and for how long (`FR-8.4`).
 *
 * Clocking yourself in and out lives in `api/auth.ts`, beside the sign-in it
 * belongs to. This is the manager's half — a read, gated on `can_access_reports`
 * by the server, because it answers a question about other people's hours.
 *
 * Minutes are counted on the server (`CLAUDE.md` §5.1). Two punches and a clock
 * look like arithmetic a screen could do, and it is: the trouble is that a
 * shift still open counts up to *now*, and "now" on a till whose clock has
 * drifted is not the now the payroll will use.
 */
import { query } from "./client";

export interface AttendanceRow {
  employee: string;
  employee_name: string;
  /** Still clocked in, so `minutes` is counting up as this is read. */
  on_duty: boolean;
  /** When the open spell began; `null` for somebody who has gone home. */
  since: string | null;
  minutes: number;
}

export interface Roster {
  /** False when the site has no HR app, so the screen can say that instead. */
  available: boolean;
  since: string | null;
  on_duty: AttendanceRow[];
  people: AttendanceRow[];
}

export function getRoster(posProfile: string, days = 1): Promise<Roster> {
  return query<Roster>("attendance.roster", { pos_profile: posProfile, days });
}
