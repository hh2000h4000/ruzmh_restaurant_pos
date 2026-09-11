/**
 * Reservation endpoints (`FR-14`, `D-191`).
 *
 * The hold — whether a booking is keeping its table right now — is worked out
 * on the server from the branch's turn time and grace period, and sent as
 * `phase`. The screen reads it; it never compares clocks of its own.
 */
import { mutate, query } from "./client";

export type ReservationStatus =
  | "pending"
  | "confirmed"
  | "seated"
  | "completed"
  | "cancelled"
  | "no_show";

export interface Reservation {
  name: string;
  customer_name: string;
  phone: string;
  party_size: number;
  customer: string | null;
  reservation_date: string;
  /** `HH:MM`. */
  reservation_time: string;
  section: string | null;
  table: string | null;
  table_number: string | null;
  status: ReservationStatus;
  /**
   * For a booking still expected: `upcoming` (its table works for walk-ins),
   * `held` (the table is kept for it), or `late` (past the grace period — the
   * table is the floor's again). `null` once seated, cancelled or missed.
   */
  phase: "upcoming" | "held" | "late" | null;
  restaurant_order: string | null;
  notes: string | null;
  cancel_reason: string | null;
  /** Recorded as a no-show by the day close, not by a host. */
  auto_no_show: 0 | 1;
  created_by_name: string | null;
}

/** What the booking form sends. `name` present means a change, not a new one. */
export interface ReservationInput {
  name?: string;
  customer_name: string;
  phone: string;
  party_size: number;
  reservation_date: string;
  reservation_time: string;
  table?: string | null;
  section?: string | null;
  notes?: string | null;
}

export function listReservations(posProfile: string, date?: string): Promise<Reservation[]> {
  return query<Reservation[]>("reservation.list_reservations", { pos_profile: posProfile, date });
}

export function saveReservation(
  posProfile: string,
  reservation: ReservationInput,
): Promise<{ reservation: string; warnings: string[] }> {
  return mutate("reservation.save_reservation", { pos_profile: posProfile, reservation });
}

export function seatReservation(payload: {
  name: string;
  pos_profile: string;
  order_type: string;
  table?: string | null;
}): Promise<{ order_name: string; reservation: string }> {
  return mutate("reservation.seat_reservation", payload);
}

/** A write like the others, so it carries a `queue_id` and a retry is safe. */
export function cancelReservation(name: string, reason: string): Promise<{ status: string }> {
  return mutate("reservation.cancel_reservation", { name, reason });
}

export function markNoShow(name: string): Promise<{ status: string }> {
  return mutate("reservation.mark_no_show", { name });
}
