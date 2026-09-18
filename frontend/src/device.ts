/**
 * Which till this machine is (`D-226`).
 *
 * The terminal used to be picked from a list of every POS Profile the cashier
 * could reach, and remembered. Nothing stopped a second machine picking the
 * same one, and then two tills sold on one terminal: a drawer counted twice,
 * receipts printing in the wrong room.
 *
 * So the machine is paired once, with a code issued on the terminal in the
 * office, and keeps the token it was handed. The token proves *this machine*;
 * the cashier still signs in with their own PIN.
 *
 * It lives in `localStorage` because it is the one fact that must survive a
 * reload on this machine and must never travel to another one. A cleared
 * browser means pairing again — which is the point: a manager decides which
 * machine is the till.
 */
const PROFILE = "rpos.pos_profile";
const TOKEN = "rpos.device_token";

export interface PairedDevice {
  posProfile: string;
  token: string;
}

/** The pairing this machine holds, or `null` when it has never been paired. */
export function pairedDevice(): PairedDevice | null {
  try {
    const posProfile = localStorage.getItem(PROFILE);
    const token = localStorage.getItem(TOKEN);
    return posProfile && token ? { posProfile, token } : null;
  } catch {
    // A browser with storage switched off still sells — it just pairs again on
    // every load rather than failing to start.
    return null;
  }
}

export function rememberDevice(device: PairedDevice): void {
  try {
    localStorage.setItem(PROFILE, device.posProfile);
    localStorage.setItem(TOKEN, device.token);
  } catch {
    /* nothing to do: the session in memory is still good for this load */
  }
}

/** Forget it — the server no longer accepts this machine on that terminal. */
export function forgetDevice(): void {
  try {
    localStorage.removeItem(PROFILE);
    localStorage.removeItem(TOKEN);
  } catch {
    /* nothing to do */
  }
}
