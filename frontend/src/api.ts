export interface AuthConfig {
  auth_required: boolean;
  demo_mode_enabled: boolean;
  google_login_enabled: boolean;
  invite_required: boolean;
  has_registered_users: boolean;
}

export interface UserProfile {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_demo: boolean;
  mcp_token: string;
  llm: {
    provider: string;
    model: string;
    base_url: string;
    using_own_key: boolean;
    masked_api_key: string;
    daily_limit: number;
    daily_used: number;
  };
}

export class AuthRequiredError extends Error {
  constructor(msg = "Bejelentkezés szükséges") {
    super(msg);
    this.name = "AuthRequiredError";
  }
}

export interface StatusInfo {
  llm_provider: string;
  llm_model: string;
  llm_key_configured: boolean;
  using_own_key?: boolean;
  ai_daily_limit?: number;
  ai_daily_used?: number;
  telegram_configured: boolean;
  cron_schedule: string;
  kifli: {
    mcp_url: string;
    authenticated: boolean;
    has_refresh_token: boolean;
    pending_login_url: string | null;
    cached_tool_count: number;
    last_error: string;
    is_demo_sandbox?: boolean;
  };
  user?: UserProfile;
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
      diet_tags?: string[];
      search_hint?: string;
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
  kcal_per_serving: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  is_public?: boolean;
  copied_count?: number;
  ingredients: Ingredient[];
}

export interface CommunityRecipe extends Recipe {
  author_name: string;
  is_mine: boolean;
}

export interface KifliRecipeItem {
  kifli_recipe_id: number;
  title: string;
  categories: string[];
  servings: number;
  duration?: string;
  image_url: string;
  ingredients_preview: string;
  healthy_score: number;
  kcal_per_serving: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

export interface KifliRecipeSearchResponse {
  is_live_kifli: boolean;
  query: string;
  recipes: KifliRecipeItem[];
  warning?: string;
}

export const HEALTHY_META: Record<
  number,
  { label: string; emoji: string; badgeClass: string }
> = {
  1: {
    label: "Kiadósabb",
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
  is_demo_sandbox?: boolean;
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
  household_size: number;
  plan_days: number;
  days_per_meal: number;
  weekly_budget_ft: number;
  daily_calorie_target?: number;
  allergens: string[];
  prefer_private_label: boolean;
  prefer_discounts_and_save_food: boolean;
  min_healthy_score: number;
  ai_recommendations_enabled: boolean;
  ai_recommendation_count: number;
  ai_recommendation_meals: string[];
  recipe_sources?: ("own" | "community" | "kifli")[];
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

export interface TinderAcceptedMatch {
  recipe_id: number;
  title: string;
  days: string[];
  meal_type: "reggeli" | "ebed" | "vacsora";
}

export interface TinderSessionState {
  code: string;
  owner_user_id?: number;
  meal_type: "reggeli" | "ebed" | "vacsora";
  target_days: string[];
  accepted_matches?: TinderAcceptedMatch[];
  is_completed?: boolean;
  created_at: string;
  p1_swiped_ids: number[];
  p2_swiped_ids: number[];
  p1_like_count: number;
  p2_like_count: number;
  deck_recipes?: Recipe[];
  matches: Recipe[];
}

export interface HouseholdMember {
  id: number;
  email: string;
  display_name: string;
  is_owner: boolean;
  is_me: boolean;
}

export interface HouseholdInfo {
  workspace_user_id: number;
  is_owner: boolean;
  owner_name: string;
  join_code: string;
  members: HouseholdMember[];
}

export interface TinderSwipeResult {
  is_match: boolean;
  matched_recipe: Recipe | null;
  session: TinderSessionState;
}

export interface PrivateLabelSwapProposal {
  old_product_id: number;
  old_name: string;
  old_quantity: number;
  old_price_ft: number;
  old_image_url: string;
  new_product_id: number;
  new_name: string;
  new_brand: string;
  new_amount: string;
  new_quantity: number;
  new_unit_price_ft: number;
  new_price_ft: number;
  savings_ft: number;
}

export interface OptimizePrivateLabelResponse {
  cart: KifliCart;
  auto_swapped: PrivateLabelSwapProposal[];
  auto_savings_ft: number;
  favorite_proposals: PrivateLabelSwapProposal[];
  message: string;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };
  const savedPin = localStorage.getItem("app_pin");
  if (savedPin) headers["X-App-Pin"] = savedPin;

  const res = await fetch(path, { credentials: "include", ...options, headers });
  if (res.status === 401) {
    const err = await res.json().catch(() => ({ detail: "Bejelentkezés szükséges!" }));
    throw new AuthRequiredError(err.detail || "Bejelentkezés szükséges!");
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
