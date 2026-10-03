import tones from "../../restaurant_pos/public/alert_tones.json";

/**
 * The bell's tone (`D-301`): notes the browser plays, not a sound file.
 *
 * The notes are data in `alert_tones.json`, which the desk's "Test the Alert
 * Sound" button reads too — the tone a manager tries is the tone the till plays.
 *
 * **One audio context for the life of the page, opened by the cashier's first
 * touch.** Browsers keep a context made before any gesture suspended (Chrome's
 * autoplay policy), and the first version made a fresh one for every chime —
 * a new audio device each time. The first tap or key on the till resumes the
 * one context, and every chime after it plays on that.
 */
interface Note {
  hz: number;
  wave: OscillatorType;
  at: number;
  for: number;
}

const TONES = tones as unknown as Record<string, Note[] | string>;

let audio: AudioContext | null = null;

function context(): AudioContext | null {
  if (audio) return audio;
  try {
    const Context =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    audio = Context ? new Context() : null;
  } catch {
    audio = null;
  }
  return audio;
}

/** Resume the context on the first touch or key, then stop listening. */
export function unlockSound(): void {
  const unlock = (): void => {
    void context()?.resume().catch(() => undefined);
    window.removeEventListener("pointerdown", unlock);
    window.removeEventListener("keydown", unlock);
  };
  window.addEventListener("pointerdown", unlock, { passive: true });
  window.addEventListener("keydown", unlock);
}

/** Play a tone at a volume from 1 to 100. Silent, never broken, where the browser will not. */
export function playTone(name: string | null | undefined, volume: number | null | undefined): void {
  try {
    const notes = TONES[name ?? ""];
    const chosen = Array.isArray(notes) ? notes : (TONES.chime as Note[]);
    const ctx = context();
    if (!ctx) return;

    const peak = Math.min(100, Math.max(1, volume ?? 70)) / 100;
    for (const note of chosen) {
      const tone = ctx.createOscillator();
      const gain = ctx.createGain();
      tone.type = note.wave;
      tone.frequency.value = note.hz;
      tone.connect(gain);
      gain.connect(ctx.destination);
      const at = ctx.currentTime + note.at;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(peak, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + note.for);
      tone.start(at);
      tone.stop(at + note.for + 0.02);
    }
  } catch {
    // No sound is better than a broken till.
  }
}

/** For tests: forget the context so the next play makes one. */
export function resetSound(): void {
  audio = null;
}
