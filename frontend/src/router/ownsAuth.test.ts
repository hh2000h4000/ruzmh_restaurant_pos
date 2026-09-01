import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The app owns signing in and signing out (`D-094`, `D-098`).
 *
 * This is a guard against a specific way of getting it wrong, and the way it
 * already went wrong once: the PIN screen was built, and two older paths were
 * left pointing at Frappe. `/api/method/logout` answers with raw JSON — a
 * cashier pressing "sign out" got a page of braces — and `/login` is the
 * ERPNext form that asks for an email address on a machine with no keyboard.
 *
 * Neither was a bug in the new screen. Both were places nobody thought to
 * change, which is what a grep-shaped test is for.
 */
const SOURCE = join(__dirname, "..");

/**
 * Navigation, not mentions.
 *
 * The first version of this matched the path anywhere in the file and failed on
 * the comments explaining why the paths are forbidden — which is its own small
 * lesson about greps. What matters is a *browser navigation* to them.
 */
const NAVIGATE = String.raw`location\s*\.\s*(?:href\s*=|assign\(|replace\()\s*`;

const FORBIDDEN = [
  {
    pattern: new RegExp(NAVIGATE + String.raw`[^;]*\/api\/method\/logout`),
    why: "sign out through the auth store, not by navigating to Frappe's endpoint",
  },
  {
    pattern: new RegExp(NAVIGATE + String.raw`[^;]*\/login`),
    why: "send the cashier to the sign-in route, not to ERPNext's login form",
  },
];

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|vue)$/.test(entry) && !entry.endsWith(".test.ts") ? [path] : [];
  });
}

describe("the app owns its own way in and out", () => {
  const files = sources(SOURCE);

  it("finds the source to check", () => {
    expect(files.length).toBeGreaterThan(20);
  });

  for (const { pattern, why } of FORBIDDEN) {
    it(`never navigates to ${pattern.source}`, () => {
      const offenders = files.filter((path) => pattern.test(readFileSync(path, "utf8")));

      expect(offenders.map((path) => path.replace(SOURCE, "src")), why).toEqual([]);
    });
  }
});
