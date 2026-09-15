/**
 * A screen whose file the browser could not fetch (`D-082`, `D-221`).
 *
 * Every view is a lazy import, so this happens two ways: **offline**, before the
 * terminal has stored the app, and **after an update**, when the build renamed
 * the files and a page that stayed open still asks for the old names.
 */
export function isMissingScreen(error: unknown): boolean {
  const message = String((error as Error | undefined)?.message ?? error);
  return /dynamically imported module|Importing a module script failed|Loading chunk/i.test(message);
}

const RELOADED_FOR = "rpos-reloaded-for";

/**
 * Whether to load the page afresh at `path` rather than say the screen is missing.
 *
 * Online it is an update, so yes — **once per path**: a second failure on the
 * same path right after a reload is not an update, and a page that reloads for
 * ever is worse than a message. `arrived` clears the mark, so the next update
 * reloads again.
 */
export function shouldReload(path: string, online: boolean = navigator.onLine): boolean {
  if (!online || remembered() === path) return false;

  remember(path);
  return true;
}

/** A screen came up: the next missing one is a new update. */
export function arrived(): void {
  remember(null);
}

function remembered(): string | null {
  try {
    return sessionStorage.getItem(RELOADED_FOR);
  } catch {
    return null;
  }
}

function remember(path: string | null): void {
  try {
    if (path === null) sessionStorage.removeItem(RELOADED_FOR);
    else sessionStorage.setItem(RELOADED_FOR, path);
  } catch {
    // Storage refused (a private window): the reload still happens, unguarded.
  }
}
