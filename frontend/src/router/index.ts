import { createRouter, createWebHistory } from "vue-router";

import { t } from "@/i18n";
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
      path: "/setup",
      name: "setup",
      component: () => import("@/views/SelectProfileView.vue"),
      meta: { requiresSession: false },
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
    {
      path: "/payment/:orderName",
      name: "payment",
      component: () => import("@/views/PaymentView.vue"),
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
 */
router.onError((error) => {
  const message = String(error?.message ?? error);
  if (!/dynamically imported module|Importing a module script failed|Loading chunk/i.test(message)) {
    return;
  }

  console.error("[rpos] a screen is not on this device:", error);
  window.alert(t("offline.screenMissing"));
});

router.beforeEach(async (to) => {
  // Who before what (`D-094`). Every other screen assumes a person: the audit
  // log records one, the permission set belongs to one, and a drawer is
  // somebody's. Probed once rather than assumed, because "not asked yet" and
  // "nobody is here" are different answers and only one of them means the
  // sign-in screen.
  const auth = useAuthStore();
  if (to.meta.requiresSignIn !== false) {
    if (!auth.known) await auth.probe(useSessionStore().profile?.name ?? null);
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

  if (to.meta.requiresSession === false) return true;

  // Every screen but setup needs the terminal configuration; without it there
  // is no branch, no menu and no permissions to render against.
  const session = useSessionStore();
  return session.isLoaded ? true : { name: "setup" };
});

export default router;
