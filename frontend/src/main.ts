import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { initLocale } from "./i18n";
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
