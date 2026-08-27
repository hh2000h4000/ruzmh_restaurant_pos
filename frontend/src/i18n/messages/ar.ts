/**
 * Arabic — the language this POS is built for.
 *
 * Typed as `Catalogue`, so a key added to `en.ts` and forgotten here stops the
 * build (`vue-tsc`) rather than reaching a till.
 */

import type { Catalogue } from "../index";

const messages: Catalogue["messages"] = {
  // Actions and chrome
  "action.cancel": "إلغاء",
  "action.back": "رجوع",
  "action.undo": "تراجع",
  "action.refresh": "تحديث",
  "action.remove": "إزالة",
  "action.authorize": "تفويض",
  "common.loading": "جارٍ التحميل…",
  "common.soon": "قيد التنفيذ",
  "common.listSeparator": "، ",
  "currency.sar": "ريال",
  "lang.other": "English",

  // Connection banner
  "conn.offline": "وضع عدم الاتصال — العمليات تُحفظ محلياً",
  "conn.signedOut": "لم يتم تسجيل الدخول",
  "conn.signIn": "تسجيل الدخول",
  "conn.syncing": "جارٍ المزامنة…",
  "conn.syncNow": "زامن الآن",
  "conn.staleConfig": "يعمل من نسخة هذا الجهاز، المحفوظة {when}.",

  // Errors raised by the API client
  "err.noCsrf": "الصفحة حُمّلت بدون رمز الحماية — سجّل الخروج وأعد تحميل الصفحة.",
  "err.offline": "لا يوجد اتصال بالخادم",
  "err.failed": "تعذّر تنفيذ الطلب ({status})",

  // Device setup
  "setup.signInFirst": "سجّل الدخول أولاً، ثم أعد المحاولة.",
  "setup.title": "تهيئة الجهاز",
  "setup.hint": "اختر نقطة البيع الخاصة بهذا الجهاز. يُسأل مرة واحدة فقط.",
  "setup.empty": "لا توجد نقطة بيع متاحة لحسابك. اطلب من المدير إضافتك إلى نقطة بيع.",

  // Home
  "home.newOrder": "افتح طلباً جديداً",
  "home.noOrderTypes": "لا توجد أنواع طلبات متاحة على هذا الجهاز.",
  "home.shiftOpen": "الوردية مفتوحة",
  "home.shiftClosed": "لا توجد وردية مفتوحة",
  "home.shiftRequired": "افتح وردية قبل استقبال الطلبات.",
  "home.shiftFromDesk": "تُفتح الوردية حالياً من شاشة Restaurant Shift في النظام.",
  "home.openOrders": "الطلبات المفتوحة",
  "home.openOrdersUnit": "طلب مفتوح",
  "type.hintTable": "يبدأ باختيار طاولة",
  "type.hintCustomer": "يتطلب عميلاً",
  "type.hintQuick": "مباشرة إلى الطلب",
  "home.openOrdersEmpty": "لا توجد طلبات مفتوحة. اختر نوع الطلب للبدء.",
  "home.openOrdersFailed": "تعذّر تحميل الطلبات المفتوحة.",
  "home.scopeMine": "طلباتي",
  "home.scopeAll": "الكل",
  "home.cashierOnDuty": "على الجهاز",
  "home.floorPlan": "مخطط الصالة",
  "home.search": "البحث في الطلبات المفتوحة…",
  "home.searchEmpty": "لا يوجد ما يطابق البحث.",
  "home.viewList": "عرض قائمة",
  "home.viewGrid": "عرض بطاقات",
  "home.sort": "الترتيب",
  "home.sortOldest": "الأقدم أولاً",
  "home.sortNewest": "الأحدث أولاً",
  "home.sortAmount": "الأعلى مبلغاً",
  "home.logout": "تسجيل خروج",
  "home.logoutConfirm": "تسجيل الخروج من هذا الجهاز؟",
  "home.logoutBody": "الطلبات المفتوحة تبقى كما هي. الكاشير التالي يسجّل دخوله على نفس الجهاز.",
  "home.appName": "نقطة البيع",
  "home.closedInvoices": "فواتير مغلقة",
  "home.reservations": "حجوزات",
  "home.shiftReport": "تقرير الوردية",

  // Order cards and statuses
  "card.table": "طاولة {number}",
  "card.amount": "المبلغ",
  "card.number": "رقم الطلب",
  "card.openedAt": "وقت الفتح",
  "card.itemCount": "عدد الأصناف",
  "card.cashier": "الكاشير",
  "card.type": "النوع",
  "card.status": "الحالة",
  "card.openOrder": "فتح الطلب",
  "card.goToTable": "الذهاب إلى مخطط الصالة",
  "status.draft": "مسودة",
  "status.active": "نشط",
  "status.in_kitchen": "في المطبخ",
  "status.pending_payment": "بانتظار الدفع",

  // Tables
  "tables.title": "الطاولات",
  "tables.table": "طاولة",
  "tables.noSection": "هذا الجهاز غير مرتبط بقسم.",
  "tables.empty": "لا توجد طاولات في هذا القسم.",
  "tables.covers": "عدد الضيوف",
  "tables.start": "فتح الطلب",
  "table.available": "فارغة",
  "table.occupied": "مشغولة",
  "table.reserved": "محجوزة",
  "table.cleaning": "تنظيف",
  "table.inactive": "خارج الخدمة",

  // Order screen
  "order.typeUnavailable": "نوع الطلب غير متاح على هذا الجهاز.",
  "order.pickTableFirst": "اختر طاولة أولاً.",
  "order.customerPending": "هذا النوع يتطلب اختيار عميل — شاشة العملاء قيد التنفيذ.",
  "order.notRouted": "لم يُوجَّه للمطبخ: {items} — ستُطبع على طابعة الكاشير.",
  "order.sendToKitchen": "إرسال للمطبخ",
  "order.pay": "دفع",
  "order.cancelOrder": "إلغاء الطلب",
  "order.voidReason": "سبب الإلغاء",
  "order.voidPlaceholder": "مثال: طلب الزبون التغيير",
  "order.voidItem": "إلغاء الصنف",
  "order.cancelBody": "سيُلغى الطلب بالكامل، وسيُبلَّغ المطبخ بما أُرسل إليه.",
  "order.confirmCancel": "تأكيد الإلغاء",
  "order.title": "الطلب",
  "order.save": "حفظ",
  "order.pendingSync": "محفوظ على هذا الجهاز — بانتظار الاتصال ليصل الخادم.",

  // Order panel
  "panel.title": "أصناف الطلب",
  "panel.inKitchen": "في المطبخ",
  "panel.addSame": "إضافة مثله",
  "panel.empty": "لم تُضف أصناف بعد.",
  "panel.count": "أصناف هذا الطلب",
  "totals.subtotal": "المجموع",
  "totals.discount": "الخصم",
  "totals.tax": "الضريبة",
  "totals.total": "الإجمالي",

  // Item picker
  "picker.search": "بحث عن صنف",
  "picker.noPrice": "بلا سعر",
  "picker.noResults": "لا نتائج.",
  "picker.empty": "لا توجد أصناف متاحة.",

  // Modifiers
  "mod.single": "اختيار واحد",
  "mod.multi": "اختيار متعدد",
  "mod.note": "ملاحظة خاصة",
  "mod.priceDelta": "الإضافة على السعر:",
  "mod.add": "إضافة للطلب",
  "mod.choose": "اختر:",

  // Payment
  "pay.title": "الدفع",
  "pay.paid": "تم الدفع",
  "pay.alreadyPaid": "هذا الطلب مدفوع — الفاتورة {invoice}",
  "pay.newOrder": "طلب جديد",
  "pay.methods": "طرق الدفع",
  "pay.forcedMethod": "هذا النوع يُدفع بـ{method} فقط.",
  "pay.received": "المبلغ المستلم (للباقي)",
  "pay.discounts": "الخصومات",
  "pay.manualDiscount": "خصم يدوي",
  "pay.discountType": "نوع الخصم",
  "pay.exceedsLimit": "يتجاوز حدّك ({limit}) — يحتاج تفويض مدير.",
  "pay.authorized": "تم التفويض",
  "pay.loyaltySoon": "الولاء غير متاح بعد.",
  "pay.summary": "ملخص الطلب",
  "pay.remaining": "المتبقي",
  "pay.change": "الباقي للعميل",
  "pay.confirm": "تأكيد الدفع وإصدار الفاتورة",
  "pay.needsManager": "يتطلب تفويض المدير",
  "pay.discountExceeds": "خصم {value} يتجاوز حدّك.",
  "pay.managerPin": "رمز المدير",
  "pay.reasonRequired": "السبب (مطلوب)",
};

/**
 * Arabic uses six plural categories and three of them below ten, so "2 صنف" is
 * wrong where "صنفان" is right. `Intl.PluralRules` chooses; this table words it.
 */
const plurals: Catalogue["plurals"] = {
  "count.items": {
    zero: "بلا أصناف",
    one: "صنف واحد",
    two: "صنفان",
    few: "{n} أصناف",
    many: "{n} صنفاً",
    other: "{n} صنف",
  },
  "count.covers": {
    zero: "بلا ضيوف",
    one: "ضيف واحد",
    two: "ضيفان",
    few: "{n} ضيوف",
    many: "{n} ضيفاً",
    other: "{n} ضيف",
  },
  "count.seats": {
    zero: "بلا كراسي",
    one: "كرسي واحد",
    two: "كرسيان",
    few: "{n} كراسي",
    many: "{n} كرسياً",
    other: "{n} كرسي",
  },
  "count.minutes": {
    zero: "الآن",
    one: "دقيقة",
    two: "دقيقتان",
    few: "{n} دقائق",
    many: "{n} دقيقة",
    other: "{n} دقيقة",
  },
  "count.openOrders": {
    zero: "لا طلبات مفتوحة",
    one: "طلب مفتوح",
    two: "طلبان مفتوحان",
    few: "{n} طلبات مفتوحة",
    many: "{n} طلباً مفتوحاً",
    other: "{n} طلب مفتوح",
  },
  "count.queued": {
    zero: "لا شيء بانتظار المزامنة",
    one: "عملية بانتظار المزامنة",
    two: "عمليتان بانتظار المزامنة",
    few: "{n} عمليات بانتظار المزامنة",
    many: "{n} عملية بانتظار المزامنة",
    other: "{n} عملية بانتظار المزامنة",
  },
  "count.syncFailed": {
    zero: "لا عمليات فاشلة",
    one: "عملية فشلت مزامنتها",
    two: "عمليتان فشلت مزامنتهما",
    few: "{n} عمليات فشلت مزامنتها",
    many: "{n} عملية فشلت مزامنتها",
    other: "{n} عملية فشلت مزامنتها",
  },
};

export default { messages, plurals };
