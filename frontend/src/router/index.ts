import { createRouter, createWebHistory } from "vue-router";

import { t } from "@/i18n";
import { arrived, isMissingScreen, shouldReload } from "@/router/missingScreen";
import { useAuthStore } from "@/stores/auth";
import { useSessionStore } from "@/stores/session";

/**
 * Routes follow the screen map in 06_UI_UX_Flow.md.
 *
 * Views are lazy so the first paint does not carry the order screen. Screens
 * that do not exist yet are absent rather than stubbed — a route to an empty
 * page hides what is missing.
 */
const router = createRouter({
  history: createWebHistory("/restaurant-pos/"),
  routes: [
    /**
     * The locked till (`D-094`).
     *
     * `requiresSession: false` because there is nothing to have a session
     * *for* until somebody signs in — this is the screen that replaces
     * ERPNext's login form, which a cashier can neither read nor type into.
     */
    {
      path: "/sign-in",
      name: "sign-in",
      component: () => import("@/views/SignInView.vue"),
      meta: { requiresSession: false, requiresSignIn: false },
    },
    {
      /**
       * Pairing comes before signing in (`D-226`).
       *
       * The PIN pad belongs to a terminal — it names the branch, and scopes the
       * PIN to the people who may work there — so a machine that does not know
       * which terminal it is cannot ask anybody to sign in. Requiring a session
       * here sent a freshly installed till to the PIN pad first, which is the
       * one screen it cannot answer.
       */
      path: "/setup",
      name: "setup",
      component: () => import("@/views/SelectProfileView.vue"),
      meta: { requiresSession: false, requiresSignIn: false },
    },
    /**
     * The till, with no bill in hand yet (D-055).
     *
     * It was a screen of its own — order types on the left, open orders on the
     * right — and both of those are panes of the order screen, so it was a
     * second way to do what this one already does. `name: "home"` is kept: it
     * is still where "back to the floor" means.
     */
    {
      path: "/",
      name: "home",
      component: () => import("@/views/OrderView.vue"),
    },
    {
      path: "/tables/:orderType",
      name: "tables",
      component: () => import("@/views/TablesView.vue"),
    },
    {
      path: "/order/new/:orderType",
      name: "new-order",
      component: () => import("@/views/OrderView.vue"),
    },
    {
      path: "/order/:orderName",
      name: "order",
      component: () => import("@/views/OrderView.vue"),
    },
    // `D-386` — paying is a column of the order screen now, beside the bill.
    // The address stays, for a bookmark or a link that still carries it.
    {
      path: "/payment/:orderName",
      name: "payment",
      redirect: (to) => ({ name: "order", params: { orderName: to.params.orderName }, query: { pane: "pay" } }),
    },
    /**
     * The screen turned around to face the guest (`FR-13`, `D-162`).
     *
     * **Neither a session nor a sign-in.** It is opened in a second window on
     * the second monitor and left there all day; if the cashier signs out, the
     * room must see the restaurant's name and not a password box. It asks the
     * server for nothing — the till beside it hands over what to show — so
     * there is nothing here for a session to authorise.
     */
    {
      path: "/customer-display",
      name: "customer-display",
      component: () => import("@/views/CustomerDisplayView.vue"),
      meta: { requiresSession: false, requiresSignIn: false },
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: { name: "home" },
    },
  ],
});

/**
 * A screen that could not be downloaded (D-082).
 *
 * **Every view here is a lazy import**, so opening one the cashier has not
 * visited fetches a chunk. Offline that fetch either comes from the service
 * worker's cache or fails — and a failed dynamic import rejects the navigation,
 * which by default is *silence*: the button looks dead, the cashier taps it
 * again, and nothing anywhere says why. That is exactly how "tapping Pay does
 * nothing" was reported.
 *
 * The message names the cause, because the fix is a person's: reconnect once so
 * the terminal can store the app (`D-078`).
 *
 * **Online it is an update, and the fix is not a person's** (`D-221`). A build
 * renames every file, so a till left open across an update asked for
 * `PaymentView-<old>.js`: Pay did nothing, and the cashier read "Failed to fetch
 * dynamically imported module" with a URL in it. The page is loaded afresh at
 * the screen that was asked for — **once**: a second failure on the same path
 * is not an update, and gets the message.
 */
router.onError((error, to) => {
  if (!isMissingScreen(error)) return;

  if (shouldReload(to.fullPath)) {
    window.location.assign(router.resolve(to).href);
    return;
  }

  console.error("[rpos] a screen is not on this device:", error);
  window.alert(t("offline.screenMissing"));
});

router.afterEach(arrived);

router.beforeEach(async (to) => {
  // **Which till, before who** (`D-226`). The PIN pad is scoped to a terminal —
  // it names the branch and the people who may work there — so a machine that
  // has not been paired cannot ask anybody to sign in.
  //
  // This used to run the other way round, and a freshly installed till went
  // straight to the PIN pad: the one screen it had no way to answer, on a
  // machine whose whole problem was that it did not know what it was. Pairing
  // is now the first screen, as it is on every POS that pairs devices.
  //
  // It remembers where it was going, so a refresh or the reload after an update
  // comes back to that screen rather than home (`D-221`).
  const session = useSessionStore();
  if (to.meta.requiresSession !== false && !session.isLoaded) {
    return to.name === "home" ? { name: "setup" } : { name: "setup", query: { next: to.fullPath } };
  }

  // Who before what (`D-094`). Every other screen assumes a person: the audit
  // log records one, the permission set belongs to one, and a drawer is
  // somebody's. Probed once rather than assumed, because "not asked yet" and
  // "nobody is here" are different answers and only one of them means the
  // sign-in screen.
  const auth = useAuthStore();
  if (to.meta.requiresSignIn !== false) {
    if (!auth.known) await auth.probe(session.profile?.name ?? null);
    if (!auth.signedIn) return { name: "sign-in" };
  }

  // **Arrive before you sell** (`D-186`). Somebody who owes a clock-in is sent
  // back to the screen that takes it, so the till cannot be reached by a
  // bookmark, the back button, or a URL typed on a keyboard the kiosk normally
  // has not got.
  //
  // The screen offers no other way forward either — this is the same rule, held
  // where a screen cannot be walked around. It is **not** a permission check:
  // the server does not refuse a sale for a missing punch, and the reason is
  // written where that decision lives (`D-186`). Only a punch that is genuinely
  // on offer stops anybody; a login on no payroll, a cashier already at work,
  // and one holding a drawer all pass straight through.
  if (to.meta.requiresSignIn !== false && auth.punchOnOffer === "in") {
    return { name: "sign-in" };
  }

  return true;
});

export default router;
