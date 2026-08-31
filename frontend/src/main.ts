import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { initLocale } from "./i18n";
import { requestDurableStorage } from "./offline/db";
import router from "./router";
import "./styles/main.css";

/**
 * Language and direction are settled before mount.
 *
 * Direction drives every CSS logical property in the app, so flipping it after
 * the first paint is visible as the whole screen jumping sides. The stored
 * device choice is enough to decide; the signed-in user's ERPNext language is
 * only consulted later, when the session payload arrives and no choice has been
 * made on this terminal yet.
 */
initLocale();

createApp(App).use(createPinia()).use(router).mount("#app");

/**
 * Keep the app itself on the device (09 §4, D-078).
 *
 * Everything RPOS does offline lives **inside** an application that has to be
 * downloaded from the server first. Without this a till survives an outage only
 * until somebody reloads, and then shows a white page with a customer waiting.
 *
 * Registered after mount, deliberately: the worker is for the *next* start, and
 * a registration that failed must never keep the app from painting this one.
 * Registration also fails outright over plain HTTP on anything but localhost —
 * which is a deployment fact worth seeing in the console rather than a reason
 * to stop.
 */
/**
 * And ask the browser not to delete what we keep there (D-079).
 *
 * Without this, an offline sale waiting in the queue is evictable data: a
 * browser clearing space would take money that has already been handed over.
 */
void requestDurableStorage();

if ("serviceWorker" in navigator) {
  // `/sw.js`, not under `/restaurant-pos/`: a worker only controls its own
  // directory and below, and that path is routed to this very page anyway.
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((cause) => {
    console.warn("[rpos] offline start-up is not available on this device:", cause);
  });
}
