/**
 * The `load_pos_session` contract (07_API_Design.md §2).
 *
 * Typed because this payload is the seam between two codebases. When the
 * backend adds or renames a field, the compiler points at every screen that
 * cared — which is the whole reason this project is in TypeScript
 * (`DECISIONS.md` D-025).
 */

export interface ThemeTokens {
  primary: string;
  primary_contrast: string;
  secondary: string;
  secondary_contrast: string;
  surface: string;
  background: string;
  text: string;
  brand_logo: string | null;
}

export interface PosProfile {
  name: string;
  company: string;
  currency: string;
  warehouse: string | null;
  selling_price_list: string | null;
  taxes_and_charges: string | null;
  customer: string | null;
  restaurant_section: string | null;
  screen_layout: string | null;
  default_printer: string | null;
  restaurant_shift: string | null;
  branch: string | null;
}

export interface RestaurantSection {
  name: string;
  title: string;
  title_ar: string;
  branch: string;
  section_type: "dine_in" | "counter" | "takeaway" | "delivery" | "bar";
  has_tables: 0 | 1;
}

export interface Branch {
  name: string;
  branch: string;
  vat_number: string | null;
  settlement_required: 0 | 1;
}

export type ButtonType = "item_group" | "item" | "goto_screen" | "action";

export interface LayoutButton {
  idx: number;
  button_type: ButtonType;
  item: string | null;
  item_group: string | null;
  goto_screen: string | null;
  action_type: string | null;
  col_start: number;
  col_span: number;
  row_start: number;
  row_span: number;
  display_text: string | null;
  display_text_ar: string | null;
  /** Per-button override from the layout designer; wins over the theme. */
  bg_color: string | null;
  text_color: string | null;
  font_size: number | null;
  image: string | null;
}

export interface ScreenLayout {
  name: string;
  title: string;
  grid_columns: number;
  grid_rows: number;
  background_color: string | null;
  buttons: LayoutButton[];
}

export interface OrderTypeField {
  label: string;
  label_ar: string;
  type: "text" | "number" | "select";
  options: string[];
  is_required: 0 | 1;
  show_at: "on_open" | "on_close" | "both";
  placeholder: string | null;
}

export interface OrderType {
  name: string;
  title: string;
  title_ar: string;
  icon: string | null;
  color: string | null;
  requires_table: 0 | 1;
  requires_cover_count: 0 | 1;
  customer_mode: "optional" | "required" | "pre_set";
  /**
   * Who owes the money (D-038).
   *
   * `walk_in` is the customer standing there; `account` is a delivery platform
   * or a company that settles on a statement. An open order changes type only
   * between two `walk_in` types — converting across would move the debt to
   * somebody who ordered nothing.
   */
  counterparty: "walk_in" | "account";
  send_to_kitchen_on: "manual" | "save" | "payment";
  sort_order: number;
  /** Overrides the terminal's price list for this type (FR-1.6). */
  selling_price_list: string | null;
  hidden_item_groups: string[];
  additional_fields: OrderTypeField[];
  payment_methods: { method: string; is_forced: 0 | 1; is_default: 0 | 1 }[];
}

export interface CatalogItem {
  item_code: string;
  item_name: string;
  pos_display_name_ar: string | null;
  display_name: string;
  item_group: string;
  stock_uom: string;
  image: string | null;
  default_production_center: string | null;
  /** The terminal's own price. `null` means none is configured — not a free
   *  item (D-020). */
  rate: number | null;
  /** Prices under any *other* list an order type sells from (FR-1.6). */
  rates: Record<string, number>;
  modifier_groups: string[];
}

export interface ItemGroup {
  name: string;
  item_group_name: string;
  parent_item_group: string | null;
  default_production_center: string | null;
}

export interface Shift {
  name: string;
  title: string;
  shift_date: string;
  shift_type: string;
  status: "open" | "closed";
  opened_by: string;
  opened_at: string;
}

export interface Promotion {
  name: string;
  title: string;
  title_ar: string;
  promotion_type: string;
  discount_value: number;
  free_item: string | null;
  apply_to: string;
  item_scope: string;
  is_auto_apply: 0 | 1;
  is_exclusive: 0 | 1;
  valid_from: string | null;
  valid_to: string | null;
  time_from: string | null;
  time_to: string | null;
}

/** Every `can_*` flag plus the two ceilings, as resolved for this user. */
export interface PosPermissions {
  [action: string]: number | string[] | undefined;
  max_item_discount_pct?: number;
  max_order_discount_pct?: number;
  roles?: string[];
}

/**
 * A note a cashier taps instead of typing (FR-2.9).
 *
 * `item` travels with a line to the one station that cooks it; `order` is
 * printed on the header of every station's ticket; `both` may be used either
 * way.
 */
export interface QuickNote {
  name: string;
  title: string;
  title_ar: string;
  scope: "item" | "order" | "both";
}

/** A hall the till may seat a table in — every one in the branch (D-040). */
export interface SectionOption {
  name: string;
  title: string;
  title_ar: string;
  section_type: RestaurantSection["section_type"];
}

export interface PosSession {
  pos_profile: PosProfile;
  /** The till's own hall: where a table-less order belongs, and the default tab. */
  restaurant_section: RestaurantSection | null;
  /** Every hall in the branch that has tables, in display order. */
  sections: SectionOption[];
  branch: Branch | null;
  screen_layout: ScreenLayout | null;
  order_types: OrderType[];
  payment_methods: { mode_of_payment: string; default: 0 | 1 }[];
  active_shift: Shift | null;
  /**
   * BR-044 — may this cashier ring a sale right now (D-054).
   *
   * The server's own answer: an open day *and* a drawer their sales land in.
   * The screens gate on this rather than reading `active_shift`, which is only
   * the day — closing a till counts the money back in while the day carries on.
   */
  can_sell: boolean;
  items: CatalogItem[];
  item_groups: ItemGroup[];
  promotions: Promotion[];
  quick_notes: QuickNote[];
  permissions: PosPermissions;
  theme: ThemeTokens;
  /** The signed-in user's ERPNext language, narrowed to what the app ships. */
  lang: "ar" | "en";
  /** Who is on this till: the login, and the name to show. */
  user: string;
  user_name: string | null;
  server_time: string;
}
