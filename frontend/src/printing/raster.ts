/**
 * The till draws its own paper (`D-415`, `docs/15`).
 *
 * Every serious system does: Toast, Square and Foodics in their apps, Odoo in
 * the browser. The server sends the paper's HTML — milliseconds to make — and
 * the browser, which already shapes Arabic correctly, turns it into the dots a
 * thermal printer takes. The server's own drawing cost about half a second a
 * page on the user's site; here it costs the till.
 *
 * Two halves, kept apart on purpose: `drawHtml` needs a real browser (a frame,
 * an SVG, a canvas); `packRaster` is arithmetic, the server's `png_to_escpos`
 * line for line, and is tested without one.
 */

/** How the server turns grey into dots, sent with the session so it is defined once. */
export interface Ink {
  threshold: number;
  bandRows: number;
}

/** A bitmap as a canvas hands it back: RGBA, row by row. */
export interface Pixels {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

/** Initialise; and feed four lines then cut, as `printing.INIT` and `FEED_AND_CUT`. */
const INIT = [0x1b, 0x40];
const FEED_AND_CUT = [0x1b, 0x64, 4, 0x1d, 0x56, 66, 0];

/**
 * Lay the receipt out `width` CSS pixels wide — one pixel per dot — and draw it.
 *
 * Through an SVG `foreignObject`, which draws HTML with the browser's own text
 * engine. Two things it does not do by itself, each found on the user's paper:
 * - **It loads nothing.** Every `<img>` is turned into a data URI first, or the
 *   logo is a blank.
 * - **Its `rem` is the SVG's, not the receipt's.** The templates set
 *   `html { font-size: 26px }` and size everything in rem, so without carrying
 *   that across the paper printed at about 60%, in two thirds of its length.
 */
export async function drawHtml(html: string, width: number): Promise<Pixels> {
  const frame = document.createElement("iframe");
  frame.setAttribute("aria-hidden", "true");
  frame.style.cssText = `position:fixed;inset-inline-start:-10000px;top:0;width:${width}px;height:10px;border:0`;
  document.body.appendChild(frame);

  try {
    const doc = frame.contentDocument!;
    doc.open();
    doc.write(html);
    doc.close();
    await inlineImages(doc);
    await doc.fonts.ready;

    const root = doc.documentElement;
    const height = Math.ceil(root.scrollHeight);
    const rootFont = getComputedStyle(root).fontSize;
    const xhtml = new XMLSerializer().serializeToString(root);

    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" style="font-size:${rootFont}">` +
      `<foreignObject width="100%" height="100%">${xhtml}</foreignObject></svg>`;
    const image = new Image();
    image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    await image.decode();

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d")!;
    // The paper, not a colour of the interface: the bitmap starts as a white
    // roll, so whatever the receipt leaves transparent prints nothing.
    context.fillStyle = "white";
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0);
    return context.getImageData(0, 0, width, height);
  } finally {
    frame.remove();
  }
}

async function inlineImages(doc: Document): Promise<void> {
  for (const image of Array.from(doc.querySelectorAll("img"))) {
    const source = image.getAttribute("src") ?? "";
    if (!source || source.startsWith("data:")) continue;
    const blob = await (await fetch(source, { credentials: "same-origin" })).blob();
    image.setAttribute("src", await asDataUri(blob));
  }
}

function asDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

/**
 * Pack a bitmap into `GS v 0` raster commands — the server's `png_to_escpos`.
 *
 * Thresholded, not dithered: dithering turns Arabic's thin strokes into
 * scattered dots (`D-109`). Transparent pixels are paper, not ink.
 */
export function packRaster(pixels: Pixels, ink: Ink, cut: boolean): Uint8Array {
  const { width, height, data } = pixels;
  const widthBytes = Math.ceil(width / 8);
  const raster = new Uint8Array(widthBytes * height);

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = (y * width + x) * 4;
      const alpha = data[at + 3] / 255;
      const grey = (0.299 * data[at] + 0.587 * data[at + 1] + 0.114 * data[at + 2]) * alpha + 255 * (1 - alpha);
      if (grey < ink.threshold) raster[y * widthBytes + (x >> 3)] |= 0x80 >> (x & 7);
    }
  }

  const parts: ArrayLike<number>[] = [INIT];
  for (let top = 0; top < height; top += ink.bandRows) {
    const rows = Math.min(ink.bandRows, height - top);
    parts.push([0x1d, 0x76, 0x30, 0, widthBytes & 0xff, widthBytes >> 8, rows & 0xff, rows >> 8]);
    parts.push(raster.subarray(top * widthBytes, (top + rows) * widthBytes));
  }
  if (cut) parts.push(FEED_AND_CUT);

  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

export function toBase64(bytes: Uint8Array): string {
  let text = "";
  for (let at = 0; at < bytes.length; at += 0x8000) {
    text += String.fromCharCode(...bytes.subarray(at, at + 0x8000));
  }
  return btoa(text);
}
