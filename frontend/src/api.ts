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
  ingredients: Ingredient[];
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
