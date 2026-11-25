export interface StatusInfo {
  llm_provider: string;
  llm_model: string;
  llm_key_configured: boolean;
  telegram_configured: boolean;
  cron_schedule: string;
  kifli: {
    mcp_url: string;
    authenticated: boolean;
    has_refresh_token: boolean;
    pending_login_url: string | null;
    cached_tool_count: number;
    last_error: string;
  };
}

export interface MealSlot {
  title: string;
  recipe_id?: number | null;
  is_recommendation?: boolean;
  custom_ingredients?: Array<{ name: string; quantity: number; unit: string; is_staple?: boolean }>;
}

export interface WeeklyPlanResponse {
  plan: {
    week_start: string;
    status: string;
    days: Record<string, { reggeli?: MealSlot; ebed?: MealSlot; vacsora?: MealSlot }>;
    adhoc_items: Array<{ name: string; quantity: number; unit: string; brand_hint?: string }>;
    recommendation_note: string;
    updated_at: string;
  } | null;
  aggregated_shopping: {
    week_start: string;
    recipe_and_adhoc_items: Array<{
      name: string;
      quantity: number;
      unit: string;
      brand_hint?: string;
      preferred_kifli_product?: { id: string; name: string } | null;
      used_in: string[];
    }>;
    general_pending_items: Array<{
      general_item_id: number;
      name: string;
      quantity: number;
      unit: string;
      brand_hint?: string;
    }>;
    general_already_in_cart: GeneralItem[];
    staples_assumed_at_home: string[];
  };
}

export interface GeneralItem {
  id: number;
  name: string;
  quantity: number;
  unit: string;
  brand_hint: string;
  status: "PENDING" | "IN_CART" | "ORDERED";
  kifli_product_id: string;
  kifli_product_name: string;
}

export interface Ingredient {
  id?: number;
  name: string;
  quantity: number;
  unit: string;
  is_staple?: boolean;
  brand_hint?: string;
}

export interface Recipe {
  id: number;
  title: string;
  categories: string[];
  servings: number;
  instructions: string;
  source_url: string;
  image_url: string;
  healthy_score: number;
  ingredients: Ingredient[];
}

export const HEALTHY_META: Record<
  number,
  { label: string; emoji: string; badgeClass: string }
> = {
  1: {
    label: "Bűnözős",
    emoji: "🍔",
    badgeClass: "bg-rose-500/15 text-rose-700 dark:text-rose-300 border-rose-500/30",
  },
  2: {
    label: "Házias",
    emoji: "🍝",
    badgeClass: "bg-orange-500/15 text-orange-700 dark:text-orange-300 border-orange-500/30",
  },
  3: {
    label: "Kiegyensúlyozott",
    emoji: "🍲",
    badgeClass: "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30",
  },
  4: {
    label: "Egészséges",
    emoji: "🥗",
    badgeClass: "bg-lime-500/15 text-lime-700 dark:text-lime-300 border-lime-500/30",
  },
  5: {
    label: "Szuper-fitt",
    emoji: "💚",
    badgeClass: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30",
  },
};

export async function uploadRecipeImage(recipeId: number, file: File): Promise<Recipe> {
  const form = new FormData();
  form.append("file", file);
  const headers: Record<string, string> = {};
  const savedPin = localStorage.getItem("app_pin");
  if (savedPin) headers["X-App-Pin"] = savedPin;

  const res = await fetch(`/api/recipes/${recipeId}/image`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Képfeltöltési hiba");
  }
  return res.json() as Promise<Recipe>;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "system";
  source: string;
  content: string;
  created_at: string;
}

export interface KifliCartItem {
  product_id: number;
  name: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  original_unit_price: number;
  sale_percent: number;
  volume: string;
  unit: string;
  category: string;
  image_url: string;
  kifli_url: string;
}

export interface KifliCart {
  connected: boolean;
  cart_id?: number;
  total_price: number;
  total_savings: number;
  min_order_price: number;
  can_checkout?: boolean;
  item_count: number;
  total_units: number;
  items: KifliCartItem[];
}

export interface PlannerSettings {
  weekly_budget_ft: number;
  allergens: string[];
  prefer_private_label: boolean;
  prefer_discounts_and_save_food: boolean;
  min_healthy_score: number;
}

export interface SmartRestockItem {
  name: string;
  kifli_product_id: string;
  brand_hint: string;
  source: string;
  order_count: number;
  avg_interval_days: number;
  days_since_last: number;
  due_ratio: number;
  urgency: "overdue" | "soon";
  reason: string;
}

export interface SmartRestockResponse {
  kifli_connected: boolean;
  kifli_orders_analyzed: number;
  local_events_analyzed: number;
  suggestions: SmartRestockItem[];
}

export interface TinderSessionState {
  code: string;
  meal_type: "reggeli" | "ebed" | "vacsora";
  target_days: string[];
  created_at: string;
  p1_swiped_ids: number[];
  p2_swiped_ids: number[];
  p1_like_count: number;
  p2_like_count: number;
  matches: Recipe[];
}

export interface TinderSwipeResult {
  is_match: boolean;
  matched_recipe: Recipe | null;
  session: TinderSessionState;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  const savedPin = localStorage.getItem("app_pin");
  if (savedPin) headers["X-App-Pin"] = savedPin;

  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    const pin = window.prompt("Add meg az APP_ACCESS_PIN kódot:");
    if (pin !== null) {
      localStorage.setItem("app_pin", pin);
      return apiFetch<T>(path, options);
    }
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Hálózati hiba történt");
  }
  return res.json() as Promise<T>;
}

export function formatFt(val: number): string {
  return new Intl.NumberFormat("hu-HU").format(Math.round(val)) + " Ft";
}
