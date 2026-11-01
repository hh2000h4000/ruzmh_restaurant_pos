/**
 * `packRaster` is the server's `png_to_escpos`, line for line (`D-415`).
 *
 * The till's paper must be the server's paper: the same threshold, the same
 * padding, the same bands, the same cut. Checked byte by byte on bitmaps small
 * enough to read.
 */
import { describe, expect, it } from "vitest";

import { packRaster, toBase64, type Pixels } from "./raster";

const INK = { threshold: 170, bandRows: 128 };
const INIT = [0x1b, 0x40];
const CUT = [0x1b, 0x64, 4, 0x1d, 0x56, 66, 0];

/** A white bitmap with the given pixels painted. */
function bitmap(width: number, height: number, paint: Record<string, [number, number, number, number]> = {}): Pixels {
  const data = new Uint8ClampedArray(width * height * 4).fill(255);
  for (const [at, rgba] of Object.entries(paint)) {
    const [x, y] = at.split(",").map(Number);
    data.set(rgba, (y * width + x) * 4);
  }
  return { width, height, data };
}

const BLACK: [number, number, number, number] = [0, 0, 0, 255];

describe("packing a bitmap for a thermal printer", () => {
  it("is INIT, one band header, the rows, and the cut", () => {
    const bytes = packRaster(bitmap(8, 1, { "0,0": BLACK }), INK, true);

    expect([...bytes]).toEqual([...INIT, 0x1d, 0x76, 0x30, 0, 1, 0, 1, 0, 0b10000000, ...CUT]);
  });

  it("pads a row to whole bytes with paper, not ink", () => {
    const bytes = packRaster(bitmap(10, 1, { "9,0": BLACK }), INK, false);

    // Ten dots are two bytes; the tenth dot is the second byte's second bit.
    expect([...bytes.slice(2, 10)]).toEqual([0x1d, 0x76, 0x30, 0, 2, 0, 1, 0]);
    expect([...bytes.slice(10)]).toEqual([0, 0b01000000]);
  });

  it("fires a dot below the threshold and leaves one above it", () => {
    const grey = (value: number): [number, number, number, number] => [value, value, value, 255];
    const bytes = packRaster(bitmap(8, 1, { "0,0": grey(169), "1,0": grey(170) }), INK, false);

    expect(bytes[bytes.length - 1]).toBe(0b10000000);
  });

  it("treats a transparent pixel as paper", () => {
    const bytes = packRaster(bitmap(8, 1, { "0,0": [0, 0, 0, 0] }), INK, false);

    expect(bytes[bytes.length - 1]).toBe(0);
  });

  it("splits a tall page into bands a cheap printer's buffer takes", () => {
    const bytes = packRaster(bitmap(8, 3), { threshold: 170, bandRows: 2 }, false);

    // Two rows, then one.
    expect([...bytes.slice(2, 10)]).toEqual([0x1d, 0x76, 0x30, 0, 1, 0, 2, 0]);
    expect([...bytes.slice(12, 20)]).toEqual([0x1d, 0x76, 0x30, 0, 1, 0, 1, 0]);
    expect(bytes.length).toBe(2 + 8 + 2 + 8 + 1);
  });

  it("leaves the cut to the printer's setting", () => {
    expect([...packRaster(bitmap(8, 1), INK, false).slice(-7)]).not.toEqual(CUT);
  });
});

describe("base64", () => {
  it("carries every byte value", () => {
    const bytes = Uint8Array.from({ length: 256 }, (_, value) => value);

    expect(Uint8Array.from(atob(toBase64(bytes)), (c) => c.charCodeAt(0))).toEqual(bytes);
  });
});
