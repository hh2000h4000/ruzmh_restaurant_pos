// @vitest-environment jsdom

/**
 * The bell's tone (`D-301`): the chosen notes, at the chosen volume, on one
 * audio context for the life of the page.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import tones from "../../restaurant_pos/public/alert_tones.json";
import { playTone, resetSound } from "@/sound";

const made = vi.fn();
const played: { hz: number; wave: string; peak: number }[] = [];

class FakeAudio {
  currentTime = 0;
  destination = {};
  constructor() {
    made();
  }
  resume() {
    return Promise.resolve();
  }
  createOscillator() {
    const tone = { type: "", frequency: { value: 0 }, connect: vi.fn(), start: vi.fn(), stop: vi.fn() };
    played.push({ hz: 0, wave: "", peak: 0 });
    const index = played.length - 1;
    queueMicrotask(() => Object.assign(played[index], { hz: tone.frequency.value, wave: tone.type }));
    return tone;
  }
  createGain() {
    const index = played.length - 1;
    return {
      gain: {
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: (value: number) => {
          if (value > 0.001) played[index].peak = value;
        },
      },
      connect: vi.fn(),
    };
  }
}

beforeEach(() => {
  resetSound();
  made.mockClear();
  played.length = 0;
  vi.stubGlobal("AudioContext", FakeAudio);
});

afterEach(() => vi.unstubAllGlobals());

describe("the bell's tone", () => {
  it("plays the chosen tone's notes at the chosen volume", async () => {
    playTone("beep", 50);
    await Promise.resolve();

    expect(played.map((note) => note.hz)).toEqual(tones.beep.map((note) => note.hz));
    expect(played.every((note) => note.wave === "square" && note.peak === 0.5)).toBe(true);
  });

  it("falls back to the chime for a tone it does not know, and keeps the volume in range", async () => {
    playTone("trumpet", 400);
    await Promise.resolve();

    expect(played.map((note) => note.hz)).toEqual(tones.chime.map((note) => note.hz));
    expect(played[0].peak).toBe(1);
  });

  it("opens one audio context for every chime, not one each", () => {
    playTone("chime", 70);
    playTone("bell", 70);

    expect(made).toHaveBeenCalledOnce();
  });
});
