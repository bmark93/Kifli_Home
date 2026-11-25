import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  CalendarDays,
  MessageSquareText,
  ShoppingBasket,
  Sparkles,
  UtensilsCrossed,
  Settings2,
  Plus,
  Minus,
  Trash2,
  CheckCircle2,
  ExternalLink,
  Send,
  Star,
  RotateCcw,
  Link2,
  Sunrise,
  Sun,
  Moon,
  ChefHat,
  PackageCheck,
  Clock,
  ShieldCheck,
  X,
  RefreshCw,
  ListChecks,
  Pencil,
  ArrowLeftRight,
  Copy,
  Terminal,
  Flame,
  ImagePlus,
  LogOut,
  KeyRound,
} from "lucide-react";
import {
  apiFetch,
  AuthRequiredError,
  formatFt,
  HEALTHY_META,
  uploadRecipeImage,
  type AuthConfig,
  type ChatMessage,
  type GeneralItem,
  type Ingredient,
  type KifliCart,
  type OptimizePrivateLabelResponse,
  type PlannerSettings,
  type PrivateLabelSwapProposal,
  type Recipe,
  type SmartRestockResponse,
  type StatusInfo,
  type UserProfile,
  type WeeklyPlanResponse,
} from "./api";
import { MealSwapSheet } from "./MealSwapSheet";
import { FoodTinderSheet } from "./FoodTinderSheet";
import { PrivateLabelSwapModal } from "./PrivateLabelSwapModal";
import { LoginView } from "./LoginView";

type TabId = "menu" | "chat" | "cart" | "general" | "recipes" | "settings";

const DAYS: Array<{ key: string; short: string; label: string }> = [
  { key: "hetfo", short: "H", label: "Hétfő" },
  { key: "kedd", short: "K", label: "Kedd" },
  { key: "szerda", short: "Sze", label: "Szerda" },
  { key: "csutortok", short: "Cs", label: "Csütörtök" },
  { key: "pentek", short: "P", label: "Péntek" },
  { key: "szombat", short: "Szo", label: "Szombat" },
  { key: "vasarnap", short: "V", label: "Vasárnap" },
];

function todayKey(): string {
  const jsDay = new Date().getDay(); // 0=Vasárnap, 1=Hétfő...
  const idx = jsDay === 0 ? 6 : jsDay - 1;
  return DAYS[idx]?.key || "hetfo";
}

/** Könnyűsúlyú markdown-jellegű szövegformázó chat buborékokhoz */
function FormattedMessage({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1.5 text-[14.5px] leading-relaxed">
      {lines.map((raw, i) => {
        const line = raw.trimEnd();
        if (!line.trim()) return <div key={i} className="h-1" />;
        if (line.startsWith("### ")) {
          return (
            <div key={i} className="pt-1 font-bold text-emerald-700 dark:text-emerald-300 text-[15px]">
              {renderBold(line.slice(4))}
            </div>
          );
        }
        if (/^\s*[\*\-•]\s+/.test(line)) {
          const clean = line.replace(/^\s*[\*\-•]\s+/, "");
          const indented = /^\s{2,}/.test(line);
          return (
            <div key={i} className={`flex gap-2 ${indented ? "pl-4 text-slate-600 dark:text-slate-300" : ""}`}>
              <span className="text-emerald-600 dark:text-emerald-400 select-none">•</span>
              <span>{renderBold(clean)}</span>
            </div>
          );
        }
        return <p key={i}>{renderBold(line)}</p>;
      })}
    </div>
  );
}

function renderBold(str: string): React.ReactNode {
  const parts = str.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, idx) =>
    p.startsWith("**") && p.endsWith("**") ? (
      <strong key={idx} className="font-semibold text-slate-950 dark:text-white">
        {p.slice(2, -2)}
      </strong>
    ) : (
      <React.Fragment key={idx}>{p}</React.Fragment>
    )
  );
}

export default function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authConfig, setAuthConfig] = useState<AuthConfig>({
    auth_required: true,
    demo_mode_enabled: true,
    google_login_enabled: false,
    invite_required: false,
    has_registered_users: true,
  });
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);

  // Per-user BYOK AI beállítások űrlap state
  const [byokProvider, setByokProvider] = useState<string>("gemini");
  const [byokModel, setByokModel] = useState<string>("gemini-3.1-flash-lite");
  const [byokBaseUrl, setByokBaseUrl] = useState<string>("");
  const [byokApiKey, setByokApiKey] = useState<string>("");

  const [activeTab, setActiveTab] = useState<TabId>("menu");
  const [selectedDay, setSelectedDay] = useState<string>(todayKey());
  const [showAllDays, setShowAllDays] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.innerWidth >= 1024 : false
  );
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    if (typeof window === "undefined") return "light";
    const saved = localStorage.getItem("kifli_theme");
    return saved === "dark" ? "dark" : "light";
  });
  const [swapTarget, setSwapTarget] = useState<{
    day: string;
    mealType: "reggeli" | "ebed" | "vacsora";
    currentTitle?: string;
  } | null>(null);

  function toggleTheme() {
    setTheme((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("kifli_theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      const meta = document.getElementById("meta-theme-color");
      if (meta) meta.setAttribute("content", next === "dark" ? "#121510" : "#6FA014");
      return next;
    });
  }

  const [status, setStatus] = useState<StatusInfo | null>(null);
  const [weekly, setWeekly] = useState<WeeklyPlanResponse | null>(null);
  const [generalItems, setGeneralItems] = useState<GeneralItem[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [cart, setCart] = useState<KifliCart | null>(null);
  const [staples, setStaples] = useState<Array<{ key: string; display_name: string }>>([]);
  const [prefs, setPrefs] = useState<
    Array<{ ingredient_key: string; ingredient_label: string; kifli_product_id: string; kifli_product_name: string }>
  >([]);

  const [busyAction, setBusyAction] = useState<string>("");
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);

  // Chat state
  const [chatInput, setChatInput] = useState("");
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  // Háztartási gyors-hozzáadó state
  const [genName, setGenName] = useState("");
  const [genBrand, setGenBrand] = useState("");
  const [genQty, setGenQty] = useState("1");
  const [genUnit, setGenUnit] = useState("db");

  // Recept szűrő + modalok (Új & Szerkesztés) + Kaja Tinder
  const [recipeFilter, setRecipeFilter] = useState<string>("");
  const [showNewRecipeSheet, setShowNewRecipeSheet] = useState(false);
  const [editingRecipeId, setEditingRecipeId] = useState<number | null>(null);
  const [tinderOpen, setTinderOpen] = useState<{
    day: string;
    mealType: "reggeli" | "ebed" | "vacsora";
  } | null>(null);
  const [showImportSheet, setShowImportSheet] = useState(false);
  const [importText, setImportText] = useState("");
  const [recTitle, setRecTitle] = useState("");
  const [recCats, setRecCats] = useState<string[]>(["ebed"]);
  const [recServings, setRecServings] = useState(2);
  const [recHealthyScore, setRecHealthyScore] = useState<number>(3);
  const [recImageUrl, setRecImageUrl] = useState<string>("");
  const [pendingImageFile, setPendingImageFile] = useState<File | null>(null);
  const [pendingImagePreview, setPendingImagePreview] = useState<string>("");
  const [recInstructions, setRecInstructions] = useState("");
  const [recSourceUrl, setRecSourceUrl] = useState("");
  const [recIngs, setRecIngs] = useState<Ingredient[]>([
    { name: "", quantity: 1, unit: "db", brand_hint: "", is_staple: false },
  ]);

  function openCreateRecipe() {
    setEditingRecipeId(null);
    setRecTitle("");
    setRecCats(["ebed"]);
    setRecServings(2);
    setRecHealthyScore(3);
    setRecImageUrl("");
    setPendingImageFile(null);
    setPendingImagePreview("");
    setRecInstructions("");
    setRecSourceUrl("");
    setRecIngs([{ name: "", quantity: 1, unit: "db", brand_hint: "", is_staple: false }]);
    setShowNewRecipeSheet(true);
  }

  function openEditRecipe(r: Recipe) {
    setEditingRecipeId(r.id);
    setRecTitle(r.title);
    setRecCats(r.categories.length ? [...r.categories] : ["ebed"]);
    setRecServings(r.servings || 2);
    setRecHealthyScore(r.healthy_score || 3);
    setRecImageUrl(r.image_url || "");
    setPendingImageFile(null);
    setPendingImagePreview("");
    setRecInstructions(r.instructions || "");
    setRecSourceUrl(r.source_url || "");
    setRecIngs(
      r.ingredients.length
        ? r.ingredients.map((i) => ({
            name: i.name,
            quantity: i.quantity,
            unit: i.unit,
            brand_hint: i.brand_hint || "",
            is_staple: Boolean(i.is_staple),
          }))
        : [{ name: "", quantity: 1, unit: "db", brand_hint: "", is_staple: false }]
    );
    setShowNewRecipeSheet(true);
  }

  // Kifli OAuth, Kamra, Tervező preferenciák & Smart Restock
  const [loginUrl, setLoginUrl] = useState<string>("");
  const [callbackUrl, setCallbackUrl] = useState<string>("");
  const [newStaple, setNewStaple] = useState<string>("");
  const [plannerSettings, setPlannerSettings] = useState<PlannerSettings>({
    weekly_budget_ft: 0,
    allergens: [],
    prefer_private_label: true,
    prefer_discounts_and_save_food: true,
    min_healthy_score: 3.4,
    ai_recommendations_enabled: true,
    ai_recommendation_count: 1,
    ai_recommendation_meals: ["ebed"],
  });
  const [smartRestock, setSmartRestock] = useState<SmartRestockResponse | null>(null);
  const [favoriteSwapModal, setFavoriteSwapModal] = useState<{
    autoSwappedCount: number;
    autoSavingsFt: number;
    proposals: PrivateLabelSwapProposal[];
  } | null>(null);
  const [lastSwapSummary, setLastSwapSummary] = useState<string>("");

  function notify(msg: string, kind: "ok" | "err" = "ok") {
    setToast({ msg, kind });
    setTimeout(() => setToast((prev) => (prev?.msg === msg ? null : prev)), 3800);
  }

  async function loadCore() {
    try {
      const [st, wp, gi, ch] = await Promise.all([
        apiFetch<StatusInfo>("/api/status"),
        apiFetch<WeeklyPlanResponse>("/api/weekly-plan"),
        apiFetch<GeneralItem[]>("/api/general-items"),
        apiFetch<ChatMessage[]>("/api/chat"),
      ]);
      setStatus(st);
      setWeekly(wp);
      setGeneralItems(gi);
      setChatMessages(ch);
      if (st.kifli.authenticated) {
        apiFetch<KifliCart>("/api/kifli/cart")
          .then(setCart)
          .catch(() => {});
      }
    } catch (e: any) {
      notify(e.message || "Betöltési hiba", "err");
    }
  }

  async function loadRecipesAndSettings() {
    try {
      const [rc, stp, prf, ps] = await Promise.all([
        apiFetch<Recipe[]>("/api/recipes"),
        apiFetch<Array<{ key: string; display_name: string }>>("/api/staples"),
        apiFetch<any[]>("/api/preferences"),
        apiFetch<PlannerSettings>("/api/planner-settings"),
      ]);
      setRecipes(rc);
      setStaples(stp);
      setPrefs(prf);
      setPlannerSettings(ps);
    } catch {
      // silent
    }
  }

  async function savePlannerSettings(patch: Partial<PlannerSettings>) {
    const merged = { ...plannerSettings, ...patch };
    setPlannerSettings(merged);
    try {
      const saved = await apiFetch<PlannerSettings>("/api/planner-settings", {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setPlannerSettings(saved);
      notify("✅ Tervező preferenciák elmentve!");
    } catch (e: any) {
      notify(e.message, "err");
    }
  }

  async function loadSmartRestock() {
    setBusyAction("restock");
    try {
      const data = await apiFetch<SmartRestockResponse>("/api/smart-restock");
      setSmartRestock(data);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleOptimizePrivateLabel() {
    setBusyAction("optimize-pl");
    setLastSwapSummary("");
    try {
      const res = await apiFetch<OptimizePrivateLabelResponse>(
        "/api/kifli/cart/optimize-private-label",
        { method: "POST" }
      );
      setCart(res.cart);
      if (res.favorite_proposals && res.favorite_proposals.length > 0) {
        setFavoriteSwapModal({
          autoSwappedCount: res.auto_swapped.length,
          autoSavingsFt: res.auto_savings_ft,
          proposals: res.favorite_proposals,
        });
      }
      if (res.auto_swapped.length > 0) {
        const names = res.auto_swapped
          .map((s) => `${s.old_name} → ${s.new_name} (-${formatFt(s.savings_ft)})`)
          .join(" · ");
        setLastSwapSummary(
          `✅ ${res.auto_swapped.length} termék azonnal Kifli saját márkára cserélve (-${formatFt(res.auto_savings_ft)}): ${names}`
        );
      }
      notify(res.message);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleApplyFavoriteSwaps(swaps: PrivateLabelSwapProposal[]) {
    setBusyAction("apply-fav-swaps");
    try {
      const res = await apiFetch<{ applied_count: number; cart: KifliCart }>(
        "/api/kifli/cart/apply-swaps",
        {
          method: "POST",
          body: JSON.stringify({
            swaps: swaps.map((s) => ({
              old_product_id: s.old_product_id,
              new_product_id: s.new_product_id,
              new_quantity: s.new_quantity,
            })),
          }),
        }
      );
      setCart(res.cart);
      const totalSaved = swaps.reduce((acc, s) => acc + s.savings_ft, 0);
      notify(`✅ ${res.applied_count} kedvelt termék lecserélve Kifli saját márkára (-${formatFt(totalSaved)})!`);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function refreshCart() {
    setBusyAction("cart-refresh");
    try {
      const c = await apiFetch<KifliCart>("/api/kifli/cart");
      setCart(c);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function bootstrapAuthAndLoad() {
    try {
      const cfg = await apiFetch<AuthConfig>("/api/auth/config");
      setAuthConfig(cfg);
      try {
        const me = await apiFetch<UserProfile>("/api/auth/me");
        setCurrentUser(me);
        setByokProvider(me.llm.provider || "gemini");
        setByokModel(me.llm.model || "gemini-3.1-flash-lite");
        setByokBaseUrl(me.llm.base_url || "");
        await Promise.all([loadCore(), loadRecipesAndSettings()]);
      } catch (e: any) {
        if (e instanceof AuthRequiredError) {
          setCurrentUser(null);
        }
      }
    } catch {
      // silent
    } finally {
      setAuthReady(true);
    }
  }

  async function handleLogout() {
    await apiFetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    setCurrentUser(null);
    setCart(null);
    setWeekly(null);
    setRecipes([]);
    setChatMessages([]);
    setGeneralItems([]);
    const cfg = await apiFetch<AuthConfig>("/api/auth/config").catch(() => authConfig);
    setAuthConfig(cfg);
  }

  async function handleSaveByok(clearKey = false) {
    setBusyAction("byok");
    try {
      const updated = await apiFetch<UserProfile>("/api/auth/llm-settings", {
        method: "PUT",
        body: JSON.stringify({
          llm_provider: clearKey ? "" : byokProvider,
          llm_model: clearKey ? "" : byokModel,
          llm_base_url: clearKey ? "" : byokBaseUrl,
          llm_api_key: clearKey ? "" : byokApiKey.trim() ? byokApiKey.trim() : null,
        }),
      });
      setCurrentUser(updated);
      setByokApiKey("");
      await loadCore();
      notify(
        clearKey
          ? "Saját AI kulcs törölve (visszaállt a szerver alapértelmezettjére)."
          : "🔑 Saját AI API kulcs titkosítva elmentve!"
      );
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  useEffect(() => {
    bootstrapAuthAndLoad();
  }, []);

  useEffect(() => {
    if (activeTab === "chat") {
      setTimeout(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }), 80);
    }
    if (activeTab === "cart" && status?.kifli.authenticated) {
      refreshCart();
    }
  }, [activeTab, chatMessages.length]);

  // --- Akciók ---
  async function handleGenerateMenu() {
    setBusyAction("generate-menu");
    try {
      await apiFetch("/api/weekly-plan/generate", { method: "POST" });
      await loadCore();
      if (currentUser?.is_demo && !currentUser.llm.using_own_key) {
        setActiveTab("chat");
        notify("🎯 Demo módban az élő AI generálás ki van kapcsolva — nézd meg a részleteket a chatben!");
      } else {
        notify("✨ Elkészült az új heti menüterv!");
      }
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleSendToKifliCart() {
    if (currentUser?.is_demo && !currentUser.llm.using_own_key) {
      await refreshCart();
      setActiveTab("cart");
      notify("🎯 Demo Kifli kosár megnyitva — próbáld ki a 🏷️ Sajátmárka-spórolás gombot!");
      return;
    }
    setBusyAction("build-cart");
    try {
      await apiFetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({
          message:
            "Kérlek keresd meg a Kifli.hu-n az összesített bevásárlólistám tételeit (az Általános PENDING listával együtt, a kiszerelésekre figyelve), tedd be őket a Kifli kosaramba, és írd meg tételesen mit raktál be és mennyi a kosár végösszege!",
        }),
      });
      await loadCore();
      await refreshCart();
      setActiveTab("cart");
      notify("🥐 A tételek bekerültek az élő Kifli.hu kosaradba!");
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleSendChat(customPrompt?: string) {
    const msg = (customPrompt ?? chatInput).trim();
    if (!msg || busyAction === "chat") return;
    if (!customPrompt) setChatInput("");
    setBusyAction("chat");

    const optimistic: ChatMessage = {
      id: Date.now(),
      role: "user",
      source: "web",
      content: msg,
      created_at: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, optimistic]);

    try {
      await apiFetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({ message: msg }),
      });
      await Promise.all([loadCore(), loadRecipesAndSettings()]);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleAddGeneral(e: React.FormEvent) {
    e.preventDefault();
    if (!genName.trim()) return;
    try {
      await apiFetch("/api/general-items", {
        method: "POST",
        body: JSON.stringify({
          name: genName.trim(),
          quantity: parseFloat(genQty || "1") || 1,
          unit: genUnit.trim() || "db",
          brand_hint: genBrand.trim(),
        }),
      });
      setGenName("");
      setGenBrand("");
      setGenQty("1");
      await loadCore();
      notify("🧻 Hozzáadva a háztartási listához!");
    } catch (err: any) {
      notify(err.message, "err");
    }
  }

  async function handleConfirmOrder() {
    try {
      const res = await apiFetch<{ cleared_count: number }>("/api/general-items/confirm-order", {
        method: "POST",
        body: JSON.stringify({ include_pending: false }),
      });
      await loadCore();
      notify(`✅ Rendelés rögzítve! ${res.cleared_count} db kosárba tett háztartási tétel végleg törölve.`);
    } catch (e: any) {
      notify(e.message, "err");
    }
  }

  async function handleCartItemQty(productId: number, newQty: number) {
    setBusyAction(`item-${productId}`);
    try {
      const updated = await apiFetch<KifliCart>("/api/kifli/cart/update", {
        method: "POST",
        body: JSON.stringify({ product_id: productId, quantity: Math.max(0, newQty) }),
      });
      setCart(updated);
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveFavoriteFromCart(productName: string, productId: number) {
    const shortKey = window.prompt(
      "Melyik alapanyag-névhez mentsem el kedvencnek? (pl. tej, kenyér, papírzsebkendő)",
      productName.split(" ").slice(0, 2).join(" ").toLowerCase()
    );
    if (!shortKey?.trim()) return;
    try {
      await apiFetch("/api/preferences", {
        method: "POST",
        body: JSON.stringify({
          ingredient_name: shortKey.trim(),
          kifli_product_id: String(productId),
          kifli_product_name: productName,
        }),
      });
      await loadRecipesAndSettings();
      notify(`⭐ Elmentve: "${shortKey.trim()}" → ${productName}`);
    } catch (e: any) {
      notify(e.message, "err");
    }
  }

  async function handleResetWeeklyPlan() {
    if (!window.confirm("Biztosan törlöd az egész heti menüt és üresre állítod?")) return;
    setBusyAction("reset-menu");
    try {
      const updated = await apiFetch<WeeklyPlanResponse>("/api/weekly-plan/reset", {
        method: "POST",
      });
      setWeekly(updated);
      notify("🗑️ Heti menü visszaállítva üresre!");
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleSaveRecipe(e: React.FormEvent) {
    e.preventDefault();
    const validIngs = recIngs.filter((i) => i.name.trim());
    if (!recTitle.trim() || !validIngs.length) {
      notify("Adj meg nevet és legalább 1 hozzávalót!", "err");
      return;
    }
    setBusyAction("save-recipe");
    const isEdit = editingRecipeId !== null;
    try {
      const saved = await apiFetch<Recipe>(
        isEdit ? `/api/recipes/${editingRecipeId}` : "/api/recipes",
        {
          method: isEdit ? "PUT" : "POST",
          body: JSON.stringify({
            title: recTitle.trim(),
            categories: recCats.length ? recCats : ["ebed"],
            servings: recServings,
            healthy_score: recHealthyScore,
            image_url: recImageUrl,
            instructions: recInstructions.trim(),
            source_url: recSourceUrl.trim(),
            ingredients: validIngs,
          }),
        }
      );
      if (pendingImageFile) {
        await uploadRecipeImage(saved.id, pendingImageFile);
      }
      setShowNewRecipeSheet(false);
      setEditingRecipeId(null);
      setPendingImageFile(null);
      setPendingImagePreview("");
      await Promise.all([loadRecipesAndSettings(), loadCore()]);
      notify(isEdit ? "✅ Recept frissítve!" : "🍲 Új recept elmentve!");
    } catch (err: any) {
      notify(err.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleImportRecipe(e: React.FormEvent) {
    e.preventDefault();
    if (!importText.trim()) return;
    setBusyAction("import-recipe");
    try {
      await apiFetch("/api/recipes/import", {
        method: "POST",
        body: JSON.stringify({ text_or_url: importText.trim() }),
      });
      setImportText("");
      setShowImportSheet(false);
      await loadRecipesAndSettings();
      notify("⚡ AI recept sikeresen kinyerve és elmentve!");
    } catch (err: any) {
      notify(err.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  async function handleManualSlotSwap(
    days: string[],
    mealType: string,
    opts: { recipeId?: number; customTitle?: string; clear?: boolean }
  ) {
    setBusyAction("manual-swap");
    try {
      const updated = await apiFetch<WeeklyPlanResponse>("/api/weekly-plan/slot", {
        method: "PUT",
        body: JSON.stringify({
          days,
          meal_type: mealType,
          recipe_id: opts.recipeId ?? null,
          custom_title: opts.customTitle ?? "",
          clear: Boolean(opts.clear),
        }),
      });
      setWeekly(updated);
      setSwapTarget(null);
      notify("⚡ Étkezés lecserélve (0 AI token)!");
    } catch (e: any) {
      notify(e.message, "err");
    } finally {
      setBusyAction("");
    }
  }

  const filteredRecipes = useMemo(() => {
    if (!recipeFilter) return recipes;
    return recipes.filter((r) => r.categories.includes(recipeFilter));
  }, [recipes, recipeFilter]);

  const pendingGeneralCount = generalItems.filter((g) => g.status === "PENDING").length;
  const inCartGeneralCount = generalItems.filter((g) => g.status === "IN_CART").length;

  const navItems: Array<{
    id: TabId;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    badge?: number | string;
  }> = [
    { id: "menu", label: "Menü", icon: CalendarDays },
    { id: "chat", label: "Séf AI", icon: MessageSquareText },
    {
      id: "cart",
      label: "Kosár",
      icon: ShoppingBasket,
      badge: cart?.item_count ? cart.item_count : undefined,
    },
    {
      id: "general",
      label: "Háztartás",
      icon: ListChecks,
      badge: pendingGeneralCount || undefined,
    },
    { id: "recipes", label: "Receptek", icon: UtensilsCrossed },
    { id: "settings", label: "Kamra", icon: Settings2 },
  ];

  if (!authReady) {
    return (
      <div className="min-h-[100dvh] bg-[#F6F6F2] dark:bg-[#121510] flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-[#7AB116] to-[#56800C] flex items-center justify-center text-3xl shadow-lg animate-pulse">
            🥐
          </div>
          <div className="text-sm font-bold text-slate-600 dark:text-slate-300">
            kifli.otthon betöltése...
          </div>
        </div>
      </div>
    );
  }

  if (authConfig.auth_required && !currentUser) {
    return (
      <LoginView
        config={authConfig}
        theme={theme}
        onToggleTheme={toggleTheme}
        onAuthenticated={async (u) => {
          setCurrentUser(u);
          setByokProvider(u.llm.provider || "gemini");
          setByokModel(u.llm.model || "gemini-3.1-flash-lite");
          setByokBaseUrl(u.llm.base_url || "");
          await Promise.all([loadCore(), loadRecipesAndSettings()]);
        }}
      />
    );
  }

  const personalMcpPath = currentUser?.mcp_token
    ? `${window.location.origin}/mcp/${currentUser.mcp_token}`
    : `${window.location.origin}/mcp`;

  return (
    <div className="min-h-[100dvh] bg-[#F6F6F2] text-[#1F241E] dark:bg-[#121510] dark:text-slate-100 flex flex-col lg:flex-row transition-colors duration-200">
      {/* TOAST ÉRTESÍTŐ */}
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 w-full max-w-md pointer-events-none">
          <div
            className={`rounded-2xl px-4 py-3 text-sm font-medium shadow-2xl border backdrop-blur-xl flex items-center gap-2.5 ${
              toast.kind === "ok"
                ? "bg-white/95 border-emerald-500/40 text-emerald-900 dark:bg-emerald-950/90 dark:text-emerald-100"
                : "bg-white/95 border-rose-500/40 text-rose-900 dark:bg-rose-950/90 dark:text-rose-100"
            }`}
          >
            <Sparkles className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            <span>{toast.msg}</span>
          </div>
        </div>
      )}

      {/* DESKTOP SIDEBAR */}
      <aside className="hidden lg:flex lg:w-64 xl:w-68 lg:flex-col lg:fixed lg:inset-y-0 bg-white dark:bg-[#171C14] border-r border-slate-200/80 dark:border-white/5 p-5 shadow-sm dark:shadow-none z-30">
        <div className="flex items-center justify-between gap-2 mb-7">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-[#7AB116] to-[#56800C] flex items-center justify-center text-2xl shadow-lg shadow-[#6FA014]/30 ring-2 ring-amber-400/40">
              🥐
            </div>
            <div>
              <div className="font-extrabold tracking-tight text-slate-900 dark:text-white leading-none text-[17px]">
                kifli<span className="text-[#6FA014] dark:text-[#8CC61F]">.otthon</span>
              </div>
              <div className="text-[11px] font-semibold text-amber-600 dark:text-amber-400 mt-1">
                Xtra Menü &amp; MCP Séf
              </div>
            </div>
          </div>

          <button
            onClick={toggleTheme}
            title={theme === "dark" ? "Váltás világos módra" : "Váltás sötét módra"}
            className="p-2.5 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-white/5 dark:hover:bg-white/10 text-slate-700 dark:text-amber-300 border border-slate-200 dark:border-white/10 transition"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>

        <nav className="space-y-1.5 flex-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-sm font-semibold transition ${
                  active
                    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30"
                    : "text-slate-600 dark:text-slate-400 hover:text-slate-950 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-white/5"
                }`}
              >
                <span className="flex items-center gap-3">
                  <Icon className="w-4 h-4" />
                  {item.label}
                </span>
                {item.badge !== undefined && (
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {status && (
          <div className="mt-auto pt-4 border-t border-slate-200 dark:border-white/5 space-y-2 text-xs text-slate-500 dark:text-slate-400">
            {currentUser && (
              <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-white/5">
                <div className="min-w-0">
                  <div className="font-bold text-slate-800 dark:text-white truncate">
                    {currentUser.display_name}
                  </div>
                  <div className="text-[10px] truncate text-slate-400">
                    {currentUser.is_demo ? "🎯 Demo Sandbox" : currentUser.email}
                  </div>
                </div>
                {authConfig.auth_required && (
                  <button
                    type="button"
                    onClick={handleLogout}
                    title="Kijelentkezés"
                    className="p-1.5 rounded-lg hover:bg-rose-500/10 text-slate-400 hover:text-rose-500 transition"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                )}
              </div>
            )}
            <div className="flex items-center justify-between">
              <span>Kifli MCP</span>
              <span
                className={
                  status.kifli.authenticated
                    ? "text-emerald-600 dark:text-emerald-400 font-semibold"
                    : "text-amber-600 dark:text-amber-400"
                }
              >
                {status.kifli.is_demo_sandbox
                  ? "🎯 Demo"
                  : status.kifli.authenticated
                  ? "● Élő"
                  : "○ Belépés"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span>AI Motor</span>
              <span className="text-slate-700 dark:text-slate-300 truncate max-w-[125px]">
                {status.llm_model}
              </span>
            </div>
          </div>
        )}
      </aside>

      {/* MOBIL TOP HEADER */}
      <header className="lg:hidden sticky top-0 z-30 bg-white/95 dark:bg-[#171C14]/90 backdrop-blur-xl border-b border-slate-200/80 dark:border-white/5 px-4 py-3 flex items-center justify-between shadow-xs dark:shadow-none">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#7AB116] to-[#56800C] flex items-center justify-center text-lg shadow-md shadow-[#6FA014]/25 ring-2 ring-amber-400/35">
            🥐
          </div>
          <div>
            <h1 className="text-[16px] font-extrabold tracking-tight leading-none text-slate-900 dark:text-white">
              kifli<span className="text-[#6FA014] dark:text-[#8CC61F]">.otthon</span>
            </h1>
            <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5 font-medium">
              {cart && cart.total_price > 0
                ? `Kosár: ${formatFt(cart.total_price)}`
                : "Heti Menü & Bevásárlás"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-xl bg-slate-100 dark:bg-white/5 border border-slate-200 dark:border-white/10 text-slate-700 dark:text-amber-300"
            title="Téma váltása"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>

          <span
            onClick={() => setActiveTab("settings")}
            className={`cursor-pointer text-[11px] font-semibold px-2.5 py-1 rounded-full border ${
              status?.kifli.authenticated
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-300"
                : "bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-300"
            }`}
          >
            {status?.kifli.is_demo_sandbox
              ? "🎯 Demo"
              : status?.kifli.authenticated
              ? "🥐 Kifli OK"
              : "⚠️ Kifli Login"}
          </span>

          {authConfig.auth_required && currentUser && (
            <button
              type="button"
              onClick={handleLogout}
              className="p-2 rounded-xl bg-slate-100 dark:bg-white/5 border border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-300"
              title="Kijelentkezés"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </header>

      {/* FŐ TARTALOM — TELJES SZÉLESSÉGŰ WIDESCREEN RESZPONZÍV ELRENDEZÉS */}
      <main className="flex-1 lg:pl-64 xl:pl-68 pb-24 lg:pb-10 w-full">
        <div className="w-full max-w-[1920px] mx-auto px-4 sm:px-6 lg:px-8 2xl:px-10 pt-4 lg:pt-6">
          {/* DEMO SANDBOX BANNER */}
          {currentUser?.is_demo && (
            <div className="mb-4 rounded-2xl bg-amber-50 dark:bg-amber-950/50 border border-amber-400/40 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 text-xs text-amber-900 dark:text-amber-100">
              <span>
                🎯 <strong>Interaktív Demo Mód:</strong> szabadon próbálgathatod a szimulált Kifli
                kosarat, a Sajátmárka-optimalizálót, a Kaja Tindert és a Smart Restockot! (Az élő AI
                chathez lépj be saját fiókkal és adj meg saját API kulcsot.)
              </span>
              <button
                type="button"
                onClick={async () => {
                  const fresh = await apiFetch<KifliCart>("/api/kifli/cart/demo-reset", {
                    method: "POST",
                  });
                  setCart(fresh);
                  notify("🔄 Demo Kifli kosár visszaállítva eredeti állapotba!");
                }}
                className="px-3 py-1 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 font-bold text-amber-900 dark:text-amber-200"
              >
                🔄 Demo kosár alaphelyzetbe
              </button>
            </div>
          )}
          {/* =================================================================
              1. TAB: HETI MENÜ & ÖSSZESÍTETT BEVÁSÁRLÓLISTA (Widescreen 2-hasábos!)
             ================================================================= */}
          {activeTab === "menu" && (
            <div className="space-y-5">
              {/* Hero Action Card */}
              <div className="rounded-3xl bg-gradient-to-br from-[#6FA014] via-[#5C870E] to-[#3F620A] dark:from-[#365314] dark:via-[#263B0F] dark:to-[#182210] border border-emerald-500/25 p-5 sm:p-6 shadow-lg text-white">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div>
                    <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-100 dark:text-emerald-300 bg-white/15 dark:bg-emerald-500/10 border border-white/20 dark:border-emerald-500/20 px-2.5 py-1 rounded-full mb-2">
                      <Sparkles className="w-3.5 h-3.5" />
                      {weekly?.plan?.week_start
                        ? `Hét kezdete: ${weekly.plan.week_start}`
                        : "Heti okos tervező · Kattints bármelyik étkezésre a 0-tokenes cseréhez!"}
                    </div>
                    <h2 className="text-lg sm:text-2xl font-bold text-white">
                      Mit eszünk ezen a héten?
                    </h2>
                    {weekly?.plan?.recommendation_note && (
                      <p className="text-xs sm:text-sm text-amber-200 mt-1">
                        🌟 {weekly.plan.recommendation_note}
                      </p>
                    )}
                  </div>

                  <div className="grid grid-cols-2 sm:flex sm:flex-wrap gap-2 shrink-0">
                    <button
                      disabled={busyAction !== ""}
                      onClick={() => setTinderOpen({ day: selectedDay, mealType: "ebed" })}
                      className="flex items-center justify-center gap-1.5 px-4 py-3 rounded-2xl bg-gradient-to-r from-rose-500 to-orange-500 hover:from-rose-400 hover:to-orange-400 active:scale-[0.98] text-xs sm:text-sm font-bold text-white shadow-lg shadow-rose-500/25 transition disabled:opacity-50"
                    >
                      <Flame className="w-4 h-4" />
                      <span>Kaja Tinder</span>
                    </button>

                    <button
                      disabled={busyAction !== ""}
                      onClick={handleGenerateMenu}
                      className="flex items-center justify-center gap-1.5 px-3.5 py-3 rounded-2xl bg-white/15 hover:bg-white/25 active:scale-[0.98] text-xs sm:text-sm font-semibold text-white border border-white/20 transition disabled:opacity-50"
                    >
                      <RefreshCw
                        className={`w-4 h-4 ${busyAction === "generate-menu" ? "animate-spin" : ""}`}
                      />
                      <span>{busyAction === "generate-menu" ? "Tervezés..." : "AI Új menü"}</span>
                    </button>

                    <button
                      disabled={busyAction !== ""}
                      onClick={handleSendToKifliCart}
                      className="flex items-center justify-center gap-1.5 px-4 py-3 rounded-2xl bg-white text-emerald-950 hover:bg-emerald-50 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 active:scale-[0.98] text-xs sm:text-sm font-bold shadow-lg transition disabled:opacity-50"
                    >
                      <ShoppingBasket className="w-4 h-4" />
                      <span>{busyAction === "build-cart" ? "Kosár épül..." : "Kifli kosárba"}</span>
                    </button>

                    <button
                      disabled={busyAction !== ""}
                      onClick={handleResetWeeklyPlan}
                      title="Heti menü törlése / visszaállítás üresre"
                      className="flex items-center justify-center gap-1.5 px-3.5 py-3 rounded-2xl bg-rose-500/20 hover:bg-rose-500/35 active:scale-[0.98] text-xs sm:text-sm font-semibold text-rose-100 border border-rose-400/30 transition disabled:opacity-50"
                    >
                      <Trash2 className="w-4 h-4" />
                      <span>Reset</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* WIDESCREEN 12-OSZLOPOS MUNKATERÜLET */}
              <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
                {/* BAL HASÁB (8-9 oszlop): Napválasztó + Napi étkezés kártyák */}
                <div className="xl:col-span-8 2xl:col-span-9 space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex gap-1.5 overflow-x-auto no-scrollbar py-1">
                      {DAYS.map((d) => {
                        const isSelected = !showAllDays && selectedDay === d.key;
                        const hasReco =
                          weekly?.plan?.days?.[d.key]?.reggeli?.is_recommendation ||
                          weekly?.plan?.days?.[d.key]?.ebed?.is_recommendation ||
                          weekly?.plan?.days?.[d.key]?.vacsora?.is_recommendation;
                        return (
                          <button
                            key={d.key}
                            onClick={() => {
                              setShowAllDays(false);
                              setSelectedDay(d.key);
                            }}
                            className={`relative shrink-0 px-3.5 py-2 rounded-2xl text-xs font-bold transition ${
                              isSelected
                                ? "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 shadow-md shadow-emerald-500/20"
                                : "bg-white dark:bg-[#1F261A] text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-white/5 hover:bg-slate-100 dark:hover:bg-white/10"
                            }`}
                          >
                            <span className="sm:hidden">{d.short}</span>
                            <span className="hidden sm:inline">{d.label}</span>
                            {hasReco && (
                              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber-400 ring-2 ring-slate-50 dark:ring-[#121510]" />
                            )}
                          </button>
                        );
                      })}
                    </div>

                    <button
                      onClick={() => setShowAllDays((v) => !v)}
                      className={`shrink-0 px-3.5 py-2 rounded-2xl text-xs font-semibold border transition ${
                        showAllDays
                          ? "bg-slate-900 text-white border-slate-900 dark:bg-white/15 dark:border-white/25 dark:text-white"
                          : "bg-white dark:bg-[#1F261A] border-slate-200 dark:border-white/5 text-slate-600 dark:text-slate-400"
                      }`}
                    >
                      {showAllDays ? "Napi fókusz" : "Mind a 7 nap"}
                    </button>
                  </div>

                  {/* Napok rácsa: Ha mind a 7 nap látszik, PC-n 2-3 oszlopos naptár-rács! */}
                  <div
                    className={
                      showAllDays
                        ? "grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4"
                        : "space-y-4"
                    }
                  >
                    {(showAllDays ? DAYS : DAYS.filter((d) => d.key === selectedDay)).map(
                      (dayObj) => {
                        const isToday = dayObj.key === todayKey();
                        const slots = weekly?.plan?.days?.[dayObj.key] || {};
                        const meals: Array<{
                          code: "reggeli" | "ebed" | "vacsora";
                          label: string;
                          icon: React.ComponentType<{ className?: string }>;
                          accent: string;
                        }> = [
                          {
                            code: "reggeli",
                            label: "Reggeli",
                            icon: Sunrise,
                            accent: "text-amber-600 dark:text-amber-400",
                          },
                          {
                            code: "ebed",
                            label: "Ebéd",
                            icon: Sun,
                            accent: "text-emerald-600 dark:text-emerald-400",
                          },
                          {
                            code: "vacsora",
                            label: "Vacsora",
                            icon: Moon,
                            accent: "text-indigo-600 dark:text-indigo-400",
                          },
                        ];

                        return (
                          <div
                            key={dayObj.key}
                            className={`rounded-3xl bg-white dark:bg-[#1C2218] border p-4 sm:p-5 space-y-3 shadow-sm dark:shadow-none ${
                              isToday
                                ? "border-emerald-500/40 ring-1 ring-emerald-500/20"
                                : "border-slate-200/80 dark:border-white/5"
                            }`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <h3 className="font-bold text-base text-slate-900 dark:text-white">
                                  {dayObj.label}
                                </h3>
                                {isToday && (
                                  <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                                    Ma
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-slate-400 dark:text-slate-500">
                                Kattints a cseréhez
                              </span>
                            </div>

                            <div
                              className={
                                showAllDays
                                  ? "space-y-2"
                                  : "grid grid-cols-1 md:grid-cols-3 gap-3"
                              }
                            >
                              {meals.map((m) => {
                                const slot = slots[m.code];
                                const MIcon = m.icon;
                                return (
                                  <button
                                    type="button"
                                    key={m.code}
                                    onClick={() =>
                                      setSwapTarget({
                                        day: dayObj.key,
                                        mealType: m.code,
                                        currentTitle: slot?.title,
                                      })
                                    }
                                    className="w-full text-left group rounded-2xl bg-slate-50 hover:bg-emerald-50/70 dark:bg-[#151912] dark:hover:bg-white/[0.04] border border-slate-200/80 hover:border-emerald-500/40 dark:border-white/5 p-3.5 flex flex-col justify-between transition cursor-pointer"
                                  >
                                    <div className="flex items-center justify-between gap-2 mb-1.5 w-full">
                                      <span
                                        className={`flex items-center gap-1.5 text-xs font-semibold ${m.accent}`}
                                      >
                                        <MIcon className="w-3.5 h-3.5" />
                                        {m.label}
                                      </span>
                                      <div className="flex items-center gap-1.5">
                                        {slot?.is_recommendation && (
                                          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-400/30">
                                            🌟 +1
                                          </span>
                                        )}
                                        <span className="text-[11px] text-slate-400 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 flex items-center gap-0.5 font-medium">
                                          <ArrowLeftRight className="w-3 h-3" />
                                        </span>
                                      </div>
                                    </div>
                                    <div className="text-sm font-semibold text-slate-800 dark:text-slate-100 leading-snug">
                                      {slot?.title || (
                                        <span className="text-slate-400 dark:text-slate-500 font-normal italic">
                                          + Recept választása...
                                        </span>
                                      )}
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        );
                      }
                    )}
                  </div>
                </div>

                {/* JOBB STICKY HASÁB (4-3 oszlop): Élő Összesített Bevásárlólista */}
                <div className="xl:col-span-4 2xl:col-span-3 xl:sticky xl:top-6 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-4 sm:p-5 space-y-4 shadow-sm dark:shadow-none">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-bold text-base text-slate-900 dark:text-white">
                        🛒 Összesített Lista
                      </h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Heti alapanyagok + háztartás
                      </p>
                    </div>
                    <span className="text-xs font-bold px-2.5 py-1 rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                      {(weekly?.aggregated_shopping.recipe_and_adhoc_items.length || 0) +
                        (weekly?.aggregated_shopping.general_pending_items.length || 0)}{" "}
                      tétel
                    </span>
                  </div>

                  {weekly?.aggregated_shopping.recipe_and_adhoc_items.length ? (
                    <div className="space-y-1.5 max-h-[52vh] overflow-y-auto pr-1">
                      {weekly.aggregated_shopping.recipe_and_adhoc_items.map((it, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between gap-2 rounded-xl bg-slate-50 dark:bg-[#151912] border border-slate-200/70 dark:border-white/5 px-3 py-2 text-xs sm:text-sm"
                        >
                          <div className="flex items-center gap-1.5 min-w-0">
                            <span className="text-slate-700 dark:text-slate-200 truncate">
                              {it.name}
                            </span>
                            {it.diet_tags?.map((dt) => (
                              <span
                                key={dt}
                                className="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-sky-500/15 text-sky-700 dark:text-sky-300 border border-sky-500/25"
                              >
                                {dt}
                              </span>
                            ))}
                          </div>
                          <span className="font-bold text-emerald-600 dark:text-emerald-400 shrink-0">
                            {it.quantity} {it.unit}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500">Még üres a heti recept-bevásárlólista.</p>
                  )}

                  {weekly?.aggregated_shopping.general_pending_items.length ? (
                    <div className="pt-3 border-t border-slate-200 dark:border-white/5">
                      <div className="text-xs font-semibold text-amber-700 dark:text-amber-300 mb-2">
                        🧻 Háztartási listáról ({weekly.aggregated_shopping.general_pending_items.length}):
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {weekly.aggregated_shopping.general_pending_items.map((g) => (
                          <span
                            key={g.general_item_id}
                            className="text-xs bg-amber-500/10 border border-amber-500/25 text-amber-800 dark:text-amber-200 px-2.5 py-1 rounded-xl"
                          >
                            {g.name} ({g.quantity} {g.unit})
                            {g.brand_hint ? ` · ${g.brand_hint}` : ""}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {weekly?.aggregated_shopping.staples_assumed_at_home.length ? (
                    <p className="text-xs text-slate-500 dark:text-slate-400 pt-2 border-t border-slate-200 dark:border-white/5">
                      🧂{" "}
                      <strong className="text-slate-700 dark:text-slate-300">
                        Kamrában feltételezve:
                      </strong>{" "}
                      {weekly.aggregated_shopping.staples_assumed_at_home.join(", ")}
                    </p>
                  ) : null}
                </div>
              </div>
            </div>
          )}

          {/* =================================================================
              2. TAB: SÉF AI CHAT (Widescreenen mellette élő Heti Menü kártya!)
             ================================================================= */}
          {activeTab === "chat" && (
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
              <div className="xl:col-span-8 flex flex-col h-[calc(100dvh-9.5rem)] lg:h-[calc(100dvh-4rem)] rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 shadow-sm dark:shadow-none overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-200 dark:border-white/5 flex items-center justify-between bg-slate-50 dark:bg-[#20271C]">
                  <div className="flex items-center gap-2.5">
                    <Sparkles className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
                    <span className="font-bold text-sm text-slate-900 dark:text-white">
                      Privát Séf &amp; Kifli Asszisztens
                    </span>
                  </div>
                  <button
                    onClick={async () => {
                      await apiFetch("/api/chat", { method: "DELETE" });
                      setChatMessages([]);
                      notify("Chat előzmények törölve");
                    }}
                    className="text-xs text-slate-500 dark:text-slate-400 hover:text-rose-500 flex items-center gap-1"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> Törlés
                  </button>
                </div>

                {/* Gyors-prompt chipek */}
                <div className="px-3 py-2 border-b border-slate-200 dark:border-white/5 flex gap-2 overflow-x-auto no-scrollbar bg-slate-100/70 dark:bg-[#151912]">
                  {[
                    "Kedd ebéd legyen inkább krumplifőzelék",
                    "Adj még hozzá 2 liter tejet a héthez",
                    "Rakd össze most a Kifli kosaramat!",
                    "Milyen jó akciók vannak most a Kiflin?",
                  ].map((q) => (
                    <button
                      key={q}
                      onClick={() => handleSendChat(q)}
                      disabled={busyAction === "chat"}
                      className="shrink-0 text-xs bg-white hover:bg-emerald-50 dark:bg-white/5 dark:hover:bg-white/10 border border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-300 px-3 py-1.5 rounded-full transition"
                    >
                      {q}
                    </button>
                  ))}
                </div>

                {/* Üzenetfolyam */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3">
                  {chatMessages.length === 0 && (
                    <div className="text-center text-slate-500 dark:text-slate-400 text-sm py-12 space-y-2">
                      <ChefHat className="w-10 h-10 mx-auto text-emerald-500/60" />
                      <p className="font-medium text-slate-800 dark:text-slate-200">
                        Írj bármit természetesen magyarul!
                      </p>
                      <p className="text-xs max-w-sm mx-auto">
                        Tipp: Sima receptcseréhez a Menü fülön ingyen (0 AI tokennel) is rákattinthatsz bármelyik étkezésre!
                      </p>
                    </div>
                  )}

                  {chatMessages.map((m) => (
                    <div
                      key={m.id}
                      className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
                    >
                      <div
                        className={`max-w-[88%] sm:max-w-[78%] rounded-2xl px-4 py-3 shadow-sm ${
                          m.role === "user"
                            ? "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-medium rounded-br-sm"
                            : "bg-slate-100 text-slate-800 dark:bg-[#263020] dark:text-slate-100 border border-slate-200/70 dark:border-white/5 rounded-bl-sm"
                        }`}
                      >
                        {m.role === "user" ? (
                          <p className="text-[14.5px] whitespace-pre-wrap">{m.content}</p>
                        ) : (
                          <FormattedMessage text={m.content} />
                        )}
                      </div>
                    </div>
                  ))}

                  {busyAction === "chat" && (
                    <div className="flex justify-start">
                      <div className="bg-slate-100 dark:bg-[#263020] border border-slate-200 dark:border-white/5 rounded-2xl rounded-bl-sm px-4 py-3 text-xs text-emerald-700 dark:text-emerald-300 flex items-center gap-2">
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        A séf dolgozik (Kifli MCP / receptek egyeztetése)...
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Input sáv */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleSendChat();
                  }}
                  className="p-3 bg-slate-50 dark:bg-[#20271C] border-t border-slate-200 dark:border-white/5 flex items-center gap-2"
                >
                  <input
                    type="text"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Írj a séfnek (pl. csere, +2 tej, kosárba)..."
                    className="flex-1 bg-white dark:bg-[#121510] text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 text-[15px] rounded-2xl px-4 py-3 border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
                  />
                  <button
                    type="submit"
                    disabled={busyAction === "chat" || !chatInput.trim()}
                    className="w-12 h-12 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 active:scale-95 flex items-center justify-center shrink-0 disabled:opacity-40 transition"
                  >
                    <Send className="w-5 h-5" />
                  </button>
                </form>
              </div>

              {/* Desktop jobb oldali élő menü-áttekintő panel */}
              <div className="hidden xl:block xl:col-span-4 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 space-y-3 max-h-[calc(100dvh-4rem)] overflow-y-auto shadow-sm dark:shadow-none">
                <h3 className="font-bold text-sm text-slate-900 dark:text-white">
                  📅 Aktuális Heti Menü (Élő nézet)
                </h3>
                <div className="space-y-2">
                  {DAYS.map((d) => {
                    const s = weekly?.plan?.days?.[d.key] || {};
                    return (
                      <div
                        key={d.key}
                        className="rounded-2xl bg-slate-50 dark:bg-[#151912] border border-slate-200/70 dark:border-white/5 p-3 text-xs space-y-1"
                      >
                        <div className="font-bold text-emerald-700 dark:text-emerald-400">
                          {d.label}
                        </div>
                        <div className="text-slate-600 dark:text-slate-300">
                          🌅 {s.reggeli?.title || "—"}
                        </div>
                        <div className="text-slate-800 dark:text-slate-100 font-medium">
                          🍲 {s.ebed?.title || "—"}
                        </div>
                        <div className="text-slate-600 dark:text-slate-300">
                          🌙 {s.vacsora?.title || "—"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* =================================================================
              3. TAB: ÉLŐ KIFLI.HU KOSÁR (Widescreen Rács + Sticky Checkout!)
             ================================================================= */}
          {activeTab === "cart" && (
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
              {/* Termékek rácsa (bal 8-9 oszlop PC-n, mobil alul) */}
              <div className="xl:col-span-8 2xl:col-span-9 order-2 xl:order-1 space-y-3">
                {lastSwapSummary && (
                  <div className="rounded-2xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-500/30 px-4 py-3 text-xs sm:text-sm text-emerald-900 dark:text-emerald-100 flex items-start justify-between gap-3">
                    <span>{lastSwapSummary}</span>
                    <button
                      type="button"
                      onClick={() => setLastSwapSummary("")}
                      className="text-emerald-700 dark:text-emerald-300 shrink-0"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}

                {!cart || cart.items.length === 0 ? (
                  <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/5 p-12 text-center space-y-3 shadow-sm dark:shadow-none">
                    <ShoppingBasket className="w-12 h-12 mx-auto text-slate-400 dark:text-slate-600" />
                    <p className="text-slate-700 dark:text-slate-300 font-semibold">
                      A Kifli kosarad jelenleg üres
                    </p>
                    <p className="text-xs text-slate-500">
                      Menj a Menü fülre, és nyomj a „Kifli kosárba” gombra!
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3">
                    {cart.items.map((item) => (
                      <div
                        key={item.product_id}
                        className="rounded-2xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-3.5 flex items-center gap-3.5 shadow-sm dark:shadow-none"
                      >
                        {item.image_url ? (
                          <img
                            src={item.image_url}
                            alt={item.name}
                            loading="lazy"
                            className="w-14 h-14 sm:w-16 sm:h-16 rounded-xl object-cover bg-white border border-slate-100 shrink-0"
                          />
                        ) : (
                          <div className="w-14 h-14 rounded-xl bg-slate-100 dark:bg-white/5 shrink-0" />
                        )}

                        <div className="flex-1 min-w-0">
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
                            {item.category}
                          </div>
                          <a
                            href={item.kifli_url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sm font-semibold text-slate-900 dark:text-white hover:text-emerald-600 dark:hover:text-emerald-300 line-clamp-2 leading-snug"
                          >
                            {item.name}
                          </a>
                          <div className="flex items-center gap-2 mt-1 flex-wrap">
                            <span className="text-sm font-bold text-emerald-600 dark:text-emerald-400">
                              {formatFt(item.line_total)}
                            </span>
                            <span className="text-xs text-slate-500">
                              ({formatFt(item.unit_price)}/db)
                            </span>
                            {item.sale_percent > 0 && (
                              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-600 dark:text-rose-300">
                                -{item.sale_percent}%
                              </span>
                            )}
                          </div>
                        </div>

                        {/* + / - / Kedvenc gombok */}
                        <div className="flex flex-col items-end gap-2 shrink-0">
                          <button
                            onClick={() => handleSaveFavoriteFromCart(item.name, item.product_id)}
                            className="text-slate-400 hover:text-amber-500 p-1"
                            title="Mentés kedvenc márkaként"
                          >
                            <Star className="w-4 h-4" />
                          </button>

                          <div className="flex items-center gap-1 bg-slate-100 dark:bg-[#121510] border border-slate-200 dark:border-white/10 rounded-xl p-1">
                            <button
                              disabled={busyAction === `item-${item.product_id}`}
                              onClick={() => handleCartItemQty(item.product_id, item.quantity - 1)}
                              className="w-7 h-7 rounded-lg hover:bg-slate-200 dark:hover:bg-white/10 flex items-center justify-center text-slate-700 dark:text-slate-300"
                            >
                              {item.quantity <= 1 ? (
                                <Trash2 className="w-3.5 h-3.5 text-rose-500" />
                              ) : (
                                <Minus className="w-3.5 h-3.5" />
                              )}
                            </button>
                            <span className="w-6 text-center text-xs font-bold text-slate-900 dark:text-white">
                              {item.quantity}
                            </span>
                            <button
                              disabled={busyAction === `item-${item.product_id}`}
                              onClick={() => handleCartItemQty(item.product_id, item.quantity + 1)}
                              className="w-7 h-7 rounded-lg hover:bg-slate-200 dark:hover:bg-white/10 flex items-center justify-center text-emerald-600 dark:text-emerald-400"
                            >
                              <Plus className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Kosár Összegző & Checkout Kártya (Sticky jobb panel PC-n) */}
              <div className="xl:col-span-4 2xl:col-span-3 order-1 xl:order-2 xl:sticky xl:top-6 rounded-3xl bg-gradient-to-br from-[#6FA014] to-[#47690C] dark:from-[#2F4712] dark:to-[#1A2412] border border-emerald-500/25 p-5 space-y-4 text-white shadow-lg">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <span className="text-xs font-semibold text-emerald-100 dark:text-emerald-400 uppercase tracking-wider">
                      Élő Kifli.hu Kosár ({cart?.item_count || 0} tétel)
                    </span>
                    <div className="text-3xl font-black text-white mt-0.5">
                      {formatFt(cart?.total_price || 0)}
                    </div>
                    {cart && cart.total_savings > 0 ? (
                      <div className="text-xs font-semibold text-amber-200 dark:text-emerald-300 mt-1">
                        🎉 Akciós megtakarítás: -{formatFt(cart.total_savings)}
                      </div>
                    ) : null}
                  </div>

                  <button
                    onClick={refreshCart}
                    disabled={busyAction === "cart-refresh"}
                    className="p-2.5 rounded-xl bg-white/15 hover:bg-white/25 border border-white/20 text-white"
                    title="Kosár frissítése"
                  >
                    <RefreshCw
                      className={`w-4 h-4 ${busyAction === "cart-refresh" ? "animate-spin" : ""}`}
                    />
                  </button>
                </div>

                {/* Heti büdzsé állapotsáv (ha be van állítva keret) */}
                {plannerSettings.weekly_budget_ft > 0 && (
                  <div className="rounded-2xl bg-black/20 p-3 space-y-1.5 text-xs">
                    <div className="flex justify-between font-semibold">
                      <span>Heti keret ({formatFt(plannerSettings.weekly_budget_ft)})</span>
                      <span
                        className={
                          (cart?.total_price || 0) > plannerSettings.weekly_budget_ft
                            ? "text-rose-200"
                            : "text-emerald-200"
                        }
                      >
                        {Math.round(
                          ((cart?.total_price || 0) / plannerSettings.weekly_budget_ft) * 100
                        )}
                        %
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-white/15 overflow-hidden">
                      <div
                        style={{
                          width: `${Math.min(
                            100,
                            Math.round(
                              ((cart?.total_price || 0) / plannerSettings.weekly_budget_ft) * 100
                            )
                          )}%`,
                        }}
                        className={`h-full rounded-full transition-all ${
                          (cart?.total_price || 0) > plannerSettings.weekly_budget_ft
                            ? "bg-rose-400"
                            : "bg-emerald-300"
                        }`}
                      />
                    </div>
                  </div>
                )}

                <div className="space-y-2.5">
                  <a
                    href="https://www.kifli.hu/rendeles/kosaram-tartalma"
                    target="_blank"
                    rel="noreferrer"
                    className="w-full flex items-center justify-center gap-2 py-3.5 px-4 rounded-2xl bg-white text-emerald-950 hover:bg-emerald-50 dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 font-bold text-sm shadow-lg transition"
                  >
                    <span>Megnyitás &amp; Fizetés a Kifli.hu-n</span>
                    <ExternalLink className="w-4 h-4" />
                  </a>

                  {cart && cart.item_count > 0 && (
                    <button
                      type="button"
                      disabled={busyAction !== ""}
                      onClick={handleOptimizePrivateLabel}
                      className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-2xl bg-white/15 hover:bg-white/25 border border-white/20 text-white font-semibold text-xs sm:text-sm transition disabled:opacity-50"
                    >
                      <Sparkles className="w-4 h-4 text-amber-200" />
                      <span>
                        {busyAction === "optimize-pl"
                          ? "Sajátmárka keresése..."
                          : "🏷️ Spórolás Kifli saját márkákkal"}
                      </span>
                    </button>
                  )}

                  {inCartGeneralCount > 0 && (
                    <button
                      onClick={handleConfirmOrder}
                      className="w-full flex items-center justify-center gap-2 py-3 px-4 rounded-2xl bg-amber-400/20 hover:bg-amber-400/30 border border-amber-300/40 text-amber-100 font-semibold text-xs sm:text-sm transition"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                      <span>Megrendeltem ({inCartGeneralCount} háztartási törlése)</span>
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* =================================================================
              4. TAB: ÁLTALÁNOS / HÁZTARTÁS (Widescreen 2-oszlopos)
             ================================================================= */}
          {activeTab === "general" && (
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
              {/* Bal: Gyors felvétel kártya */}
              <form
                onSubmit={handleAddGeneral}
                className="xl:col-span-4 xl:sticky xl:top-6 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 space-y-3 shadow-sm dark:shadow-none"
              >
                <div className="flex items-center justify-between">
                  <h2 className="font-bold text-base text-slate-900 dark:text-white">
                    🧻 Mit kell venni otthonra?
                  </h2>
                  <span className="text-[11px] text-slate-500 dark:text-slate-400">Anti-loop</span>
                </div>

                <input
                  type="text"
                  value={genName}
                  onChange={(e) => setGenName(e.target.value)}
                  placeholder="Pl. Papírzsebkendő, Domestos, Elem..."
                  className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 rounded-2xl px-4 py-3 text-[15px] border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
                  required
                />

                <input
                  type="text"
                  value={genBrand}
                  onChange={(e) => setGenBrand(e.target.value)}
                  placeholder="Pontos márka (opc., pl. Zewa Deluxe)"
                  className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-slate-500 rounded-2xl px-3.5 py-2.5 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
                />

                <div className="grid grid-cols-12 gap-2">
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    value={genQty}
                    onChange={(e) => setGenQty(e.target.value)}
                    className="col-span-4 bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white text-center rounded-2xl px-2 py-2.5 text-sm border border-slate-200 dark:border-white/10"
                  />
                  <input
                    type="text"
                    value={genUnit}
                    onChange={(e) => setGenUnit(e.target.value)}
                    placeholder="db"
                    className="col-span-4 bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white text-center rounded-2xl px-2 py-2.5 text-sm border border-slate-200 dark:border-white/10"
                  />
                  <button
                    type="submit"
                    className="col-span-4 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 active:scale-95 font-bold text-sm flex items-center justify-center gap-1"
                  >
                    <Plus className="w-4 h-4" /> Felír
                  </button>
                </div>
              </form>

              {/* Jobb: Smart Restock + Státusz sáv + többoszlopos lista */}
              <div className="xl:col-span-8 space-y-4">
                {/* 🧠 Smart Restock Fogyás-előrejelző (0 AI token!) */}
                <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-4 sm:p-5 space-y-3 shadow-sm dark:shadow-none">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="font-bold text-sm sm:text-base text-slate-900 dark:text-white">
                        🧠 Smart Restock — Fogyás-előrejelző (0 AI token)
                      </h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Kiszámolja a korábbi Kifli rendeléseidből és háztartási előzményeidből, mi fogyhatott el épp itthon.
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={busyAction === "restock"}
                      onClick={loadSmartRestock}
                      className="px-3.5 py-2 rounded-xl bg-emerald-600/15 hover:bg-emerald-600/25 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 font-bold text-xs flex items-center gap-1.5"
                    >
                      <RefreshCw
                        className={`w-3.5 h-3.5 ${busyAction === "restock" ? "animate-spin" : ""}`}
                      />
                      <span>{busyAction === "restock" ? "Elemzés..." : "Elemzés futtatása"}</span>
                    </button>
                  </div>

                  {smartRestock && (
                    smartRestock.suggestions.length === 0 ? (
                      <p className="text-xs text-slate-500 dark:text-slate-400 pt-1">
                        Még nincs elég ismétlődő rendelési adat ({smartRestock.kifli_orders_analyzed} Kifli rendelés + {smartRestock.local_events_analyzed} helyi tétel elemezve). 2–3 rendelés után automatikusan előrejelzi a fogyó tételeket!
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                        {smartRestock.suggestions.map((sug, idx) => (
                          <div
                            key={idx}
                            className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-3 flex items-center justify-between gap-2"
                          >
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                                    sug.urgency === "overdue"
                                      ? "bg-rose-500/15 text-rose-600 dark:text-rose-300"
                                      : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                                  }`}
                                >
                                  {sug.urgency === "overdue" ? "Esedékes" : "Hamarosan"}
                                </span>
                                <span className="font-semibold text-xs text-slate-900 dark:text-white truncate">
                                  {sug.name}
                                </span>
                              </div>
                              <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                                {sug.reason}
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={async () => {
                                await apiFetch("/api/general-items", {
                                  method: "POST",
                                  body: JSON.stringify({
                                    name: sug.name,
                                    quantity: 1,
                                    unit: "db",
                                    brand_hint: sug.brand_hint,
                                  }),
                                });
                                await Promise.all([loadCore(), loadSmartRestock()]);
                                notify(`🧻 Felírva: ${sug.name}`);
                              }}
                              className="shrink-0 px-3 py-1.5 rounded-xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs"
                            >
                              + Felír
                            </button>
                          </div>
                        ))}
                      </div>
                    )
                  )}
                </div>

                {inCartGeneralCount > 0 && (
                  <div className="rounded-2xl bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-500/30 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="text-xs sm:text-sm text-emerald-900 dark:text-emerald-100">
                      <strong>{inCartGeneralCount} db háztartási tétel</strong> már bekerült a Kifli kosaradba! Ha megrendelted, nyomj ide, hogy végleg törlődjenek:
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={handleConfirmOrder}
                        className="px-4 py-2.5 rounded-xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs flex items-center gap-1.5"
                      >
                        <CheckCircle2 className="w-4 h-4" /> Megrendeltem
                      </button>
                      <button
                        onClick={async () => {
                          await apiFetch("/api/general-items/revert-cart", { method: "POST" });
                          await loadCore();
                          notify("Visszaállítva várakozóra");
                        }}
                        className="px-3 py-2.5 rounded-xl bg-slate-200 dark:bg-white/10 text-slate-700 dark:text-slate-200 text-xs flex items-center gap-1"
                        title="Vissza várakozóra"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                )}

                {generalItems.length === 0 ? (
                  <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/5 p-10 text-center text-slate-500 dark:text-slate-400 text-sm shadow-sm dark:shadow-none">
                    Minden megvan itthon — jelenleg üres az egyszeri háztartási lista! ✨
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {generalItems.map((g) => (
                      <div
                        key={g.id}
                        className="rounded-2xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 px-4 py-3.5 flex items-center justify-between gap-3 shadow-sm dark:shadow-none"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            {g.status === "IN_CART" ? (
                              <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-sky-500/15 text-sky-700 dark:text-sky-300 border border-sky-400/25">
                                <PackageCheck className="w-3 h-3" /> Kosárban
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-400/25">
                                <Clock className="w-3 h-3" /> Várakozik
                              </span>
                            )}
                            <span className="font-semibold text-slate-900 dark:text-white">
                              {g.name}
                            </span>
                            <span className="text-xs text-emerald-600 dark:text-emerald-400 font-bold">
                              {g.quantity} {g.unit}
                            </span>
                          </div>
                          {(g.brand_hint || g.kifli_product_name) && (
                            <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 truncate">
                              {g.kifli_product_name
                                ? `→ ${g.kifli_product_name}`
                                : `Kért márka: ${g.brand_hint}`}
                            </div>
                          )}
                        </div>

                        <button
                          onClick={async () => {
                            await apiFetch(`/api/general-items/${g.id}`, { method: "DELETE" });
                            await loadCore();
                          }}
                          className="p-2 rounded-xl text-slate-400 hover:text-rose-500 hover:bg-slate-100 dark:hover:bg-white/5 shrink-0"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* =================================================================
              5. TAB: RECEPTEK (Widescreen 4-oszlopos rács + Szerkesztés!)
             ================================================================= */}
          {activeTab === "recipes" && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
                  {[
                    { v: "", l: "Összes" },
                    { v: "reggeli", l: "🌅 Reggeli" },
                    { v: "ebed", l: "🍲 Ebéd" },
                    { v: "vacsora", l: "🌙 Vacsora" },
                  ].map((f) => (
                    <button
                      key={f.v}
                      onClick={() => setRecipeFilter(f.v)}
                      className={`px-3.5 py-2 rounded-2xl text-xs font-bold transition ${
                        recipeFilter === f.v
                          ? "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 shadow-sm"
                          : "bg-white dark:bg-[#1C2218] text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-white/5"
                      }`}
                    >
                      {f.l}
                    </button>
                  ))}
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => setShowImportSheet(true)}
                    className="px-3.5 py-2 rounded-2xl bg-white hover:bg-emerald-50 dark:bg-white/10 dark:hover:bg-white/15 text-xs font-semibold text-emerald-700 dark:text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5"
                  >
                    <Link2 className="w-3.5 h-3.5" /> AI Import
                  </button>
                  <button
                    onClick={openCreateRecipe}
                    className="px-3.5 py-2 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 text-xs font-bold flex items-center gap-1 shadow-sm"
                  >
                    <Plus className="w-4 h-4" /> Új recept
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
                {filteredRecipes.map((r) => {
                  const hm = HEALTHY_META[r.healthy_score || 3] || HEALTHY_META[3];
                  return (
                    <div
                      key={r.id}
                      className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 overflow-hidden flex flex-col justify-between shadow-sm dark:shadow-none"
                    >
                      <div>
                        {r.image_url && (
                          <div
                            onClick={() => openEditRecipe(r)}
                            className="h-36 w-full overflow-hidden cursor-pointer relative"
                          >
                            <img
                              src={r.image_url}
                              alt={r.title}
                              loading="lazy"
                              className="w-full h-full object-cover hover:scale-105 transition duration-300"
                            />
                          </div>
                        )}
                        <div className="p-4">
                          <div className="flex items-start justify-between gap-2">
                            <h3
                              onClick={() => openEditRecipe(r)}
                              className="font-bold text-slate-900 dark:text-white leading-snug cursor-pointer hover:text-emerald-600 dark:hover:text-emerald-300 transition"
                            >
                              {r.title}
                            </h3>
                            <div className="flex items-center gap-1 shrink-0">
                              <button
                                onClick={() => openEditRecipe(r)}
                                className="text-slate-500 hover:text-emerald-600 dark:text-slate-400 dark:hover:text-emerald-300 hover:bg-slate-100 dark:hover:bg-white/5 rounded-lg p-1.5 transition"
                                title="Recept szerkesztése"
                              >
                                <Pencil className="w-4 h-4" />
                              </button>
                              <button
                                onClick={async () => {
                                  await apiFetch(`/api/recipes/${r.id}`, { method: "DELETE" });
                                  await Promise.all([loadRecipesAndSettings(), loadCore()]);
                                  notify("Recept törölve");
                                }}
                                className="text-slate-400 hover:text-rose-500 hover:bg-slate-100 dark:hover:bg-white/5 rounded-lg p-1.5 transition"
                                title="Recept törlése"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            </div>
                          </div>

                          <div className="flex flex-wrap gap-1.5 mt-1.5">
                            <span
                              className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${hm.badgeClass}`}
                            >
                              {hm.emoji} {r.healthy_score || 3}/5 · {hm.label}
                            </span>
                            {r.categories.map((c) => (
                              <span
                                key={c}
                                className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-700 dark:bg-white/5 dark:text-emerald-300"
                              >
                                {c}
                              </span>
                            ))}
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-400">
                              {r.servings} adag
                            </span>
                          </div>

                          <div className="flex flex-wrap gap-1.5 mt-3">
                            {r.ingredients.map((ing, i) => (
                              <span
                                key={i}
                                className="text-xs px-2.5 py-1 rounded-xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/5 text-slate-700 dark:text-slate-300"
                              >
                                {ing.name}{" "}
                                <span className="text-slate-400 dark:text-slate-500">
                                  {ing.quantity} {ing.unit}
                                </span>
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>

                      {r.instructions && (
                        <p className="text-xs text-slate-500 dark:text-slate-400 border-t border-slate-100 dark:border-white/5 px-4 py-2.5">
                          {r.instructions}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* =================================================================
              6. TAB: KIFLI MCP OAUTH, KAMRA & KEDVENC MÁRKÁK (Widescreen 3-hasábos!)
             ================================================================= */}
          {activeTab === "settings" && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
              {/* Kifli OAuth kártya */}
              <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 space-y-4 shadow-sm dark:shadow-none">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                    <h2 className="font-bold text-base text-slate-900 dark:text-white">
                      Kifli.hu MCP
                    </h2>
                  </div>
                  <span
                    className={`text-xs font-bold px-3 py-1 rounded-full ${
                      status?.kifli.authenticated
                        ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                        : "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                    }`}
                  >
                    {status?.kifli.authenticated ? "Csatlakoztatva" : "Nincs belépve"}
                  </span>
                </div>

                <p className="text-xs text-slate-500 dark:text-slate-400">
                  OAuth 2.1 PKCE kapcsolat: a jelszavadat soha nem látja és nem tárolja az app, a frissítő token pedig automatikusan megújul a szerveren.
                </p>

                <div className="flex flex-wrap gap-2.5">
                  <button
                    onClick={async () => {
                      const res = await apiFetch<{ login_url: string }>("/api/kifli/login", {
                        method: "POST",
                      });
                      setLoginUrl(res.login_url);
                      window.open(res.login_url, "_blank");
                    }}
                    className="px-4 py-2.5 rounded-2xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs"
                  >
                    {status?.kifli.authenticated ? "Újracsatlakozás" : "1. Belépés a Kifli.hu-ra"}
                  </button>

                  {status?.kifli.authenticated && (
                    <button
                      onClick={async () => {
                        await apiFetch("/api/kifli/logout", { method: "POST" });
                        await loadCore();
                        notify("Kijelentkezve a Kifli MCP-ből");
                      }}
                      className="px-4 py-2.5 rounded-2xl bg-slate-100 dark:bg-white/5 text-slate-700 dark:text-slate-300 text-xs"
                    >
                      Kijelentkezés
                    </button>
                  )}
                </div>

                {loginUrl && (
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      try {
                        await apiFetch("/api/kifli/callback", {
                          method: "POST",
                          body: JSON.stringify({ callback_url: callbackUrl }),
                        });
                        setLoginUrl("");
                        setCallbackUrl("");
                        await loadCore();
                        notify("✅ Kifli.hu sikeresen összekötve!");
                      } catch (err: any) {
                        notify(err.message, "err");
                      }
                    }}
                    className="space-y-2 pt-3 border-t border-slate-200 dark:border-white/5"
                  >
                    <p className="text-xs text-amber-700 dark:text-amber-200">
                      Ha távoli gépről vagy telefonról léptél be, másold be ide a kapott{" "}
                      <code>http://localhost:3334/oauth/callback?code=...</code> címet:
                    </p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={callbackUrl}
                        onChange={(e) => setCallbackUrl(e.target.value)}
                        placeholder="http://localhost:3334/oauth/callback?code=..."
                        className="flex-1 bg-slate-100 dark:bg-[#121510] rounded-xl px-3 py-2 text-xs border border-slate-200 dark:border-white/10"
                        required
                      />
                      <button
                        type="submit"
                        className="px-4 py-2 rounded-xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs"
                      >
                        Mentés
                      </button>
                    </div>
                  </form>
                )}
              </div>

              {/* Kamra alapanyagok */}
              <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 space-y-3 shadow-sm dark:shadow-none">
                <h3 className="font-bold text-base text-slate-900 dark:text-white">
                  🧂 Kamra-alapanyagok
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Ezeket alapból nem dobálja be minden héten a Kifli kosárba (só, bors, olaj, liszt...).
                </p>
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    if (!newStaple.trim()) return;
                    await apiFetch("/api/staples", {
                      method: "POST",
                      body: JSON.stringify({ name: newStaple.trim() }),
                    });
                    setNewStaple("");
                    await loadRecipesAndSettings();
                  }}
                  className="flex gap-2"
                >
                  <input
                    type="text"
                    value={newStaple}
                    onChange={(e) => setNewStaple(e.target.value)}
                    placeholder="Pl. mustár, fahéj..."
                    className="flex-1 bg-slate-100 dark:bg-[#121510] rounded-2xl px-4 py-2.5 text-sm border border-slate-200 dark:border-white/10"
                  />
                  <button
                    type="submit"
                    className="px-4 py-2.5 rounded-2xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs shrink-0"
                  >
                    + Hozzáad
                  </button>
                </form>

                <div className="flex flex-wrap gap-2 pt-1">
                  {staples.map((s) => (
                    <span
                      key={s.key}
                      className="inline-flex items-center gap-1.5 text-xs bg-slate-100 dark:bg-[#121510] border border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-200 px-3 py-1.5 rounded-full"
                    >
                      {s.display_name}
                      <button
                        onClick={async () => {
                          await apiFetch(`/api/staples/${encodeURIComponent(s.key)}`, {
                            method: "DELETE",
                          });
                          await loadRecipesAndSettings();
                        }}
                        className="text-slate-400 hover:text-rose-500"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              {/* Kedvenc Kifli termékek */}
              <div className="rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 space-y-3 shadow-sm dark:shadow-none">
                <h3 className="font-bold text-base text-slate-900 dark:text-white">
                  ⭐ Kedvenc Márkák
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  A Kosár fülön bármelyik terméknél rábökhetsz a ⭐ csillagra, és legközelebb mindig azt a márkát választja az AI!
                </p>
                {prefs.length === 0 ? (
                  <p className="text-xs text-slate-500 italic">Még nincs rögzített kedvenc termék.</p>
                ) : (
                  <div className="space-y-2">
                    {prefs.map((p) => (
                      <div
                        key={p.ingredient_key}
                        className="flex items-center justify-between rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/5 px-3.5 py-2.5 text-xs"
                      >
                        <div>
                          <strong className="text-emerald-700 dark:text-emerald-300">
                            {p.ingredient_label}
                          </strong>{" "}
                          → <span className="text-slate-700 dark:text-slate-200">{p.kifli_product_name}</span>
                        </div>
                        <button
                          onClick={async () => {
                            await apiFetch(`/api/preferences/${encodeURIComponent(p.ingredient_key)}`, {
                              method: "DELETE",
                            });
                            await loadRecipesAndSettings();
                          }}
                          className="text-slate-400 hover:text-rose-500 p-1"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 4. Kártya (Teljes szélességű): 🥗 TERVEZŐ PREFERENCIÁK (Büdzsé, Allergének, Sajátmárka, Akciók) */}
              <div className="lg:col-span-3 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 sm:p-6 space-y-4 shadow-sm dark:shadow-none">
                <div>
                  <h3 className="font-bold text-base text-slate-900 dark:text-white">
                    🥗 Heti Tervező &amp; Kosár Preferenciák (Büdzsé · Allergének · Sajátmárka · Akciók)
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    Az AI séf heti menütervezéskor és Kifli kosárépítéskor szigorúan betartja ezeket a szabályokat.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                  {/* Heti büdzsé */}
                  <div className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-3.5 space-y-2">
                    <label className="text-xs font-bold text-slate-700 dark:text-slate-300">
                      💰 Heti büdzsé limit (Ft, 0 = nincs limit)
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="number"
                        step={1000}
                        min={0}
                        value={plannerSettings.weekly_budget_ft}
                        onChange={(e) =>
                          setPlannerSettings((p) => ({
                            ...p,
                            weekly_budget_ft: Math.max(0, parseInt(e.target.value || "0", 10)),
                          }))
                        }
                        className="flex-1 bg-white dark:bg-[#1C2218] text-slate-900 dark:text-white rounded-xl px-3 py-2 text-sm border border-slate-200 dark:border-white/10"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          savePlannerSettings({ weekly_budget_ft: plannerSettings.weekly_budget_ft })
                        }
                        className="px-3 py-2 rounded-xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs"
                      >
                        Ment
                      </button>
                    </div>
                  </div>

                  {/* Min. Healthy Score */}
                  <div className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-3.5 space-y-2">
                    <div className="flex justify-between text-xs font-bold text-slate-700 dark:text-slate-300">
                      <span>💚 Cél heti Healthy Score</span>
                      <span className="text-emerald-600 dark:text-emerald-400">
                        {plannerSettings.min_healthy_score.toFixed(1)} / 5.0
                      </span>
                    </div>
                    <input
                      type="range"
                      min={1.5}
                      max={5.0}
                      step={0.1}
                      value={plannerSettings.min_healthy_score}
                      onChange={(e) =>
                        setPlannerSettings((p) => ({
                          ...p,
                          min_healthy_score: parseFloat(e.target.value),
                        }))
                      }
                      onMouseUp={() =>
                        savePlannerSettings({ min_healthy_score: plannerSettings.min_healthy_score })
                      }
                      onTouchEnd={() =>
                        savePlannerSettings({ min_healthy_score: plannerSettings.min_healthy_score })
                      }
                      className="w-full accent-emerald-500"
                    />
                  </div>

                  {/* Sajátmárka + Akciók kapcsolók */}
                  <div className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-3.5 space-y-2.5">
                    <label className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200 cursor-pointer">
                      <span>🏷️ Kifli sajátmárkák előnyben (Miil, Moddia, Yutto)</span>
                      <input
                        type="checkbox"
                        checked={plannerSettings.prefer_private_label}
                        onChange={(e) =>
                          savePlannerSettings({ prefer_private_label: e.target.checked })
                        }
                        className="w-4 h-4 accent-emerald-500"
                      />
                    </label>
                    <label className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200 cursor-pointer">
                      <span>♻️ Akciók &amp; Mentsd meg az ételt előnyben</span>
                      <input
                        type="checkbox"
                        checked={plannerSettings.prefer_discounts_and_save_food}
                        onChange={(e) =>
                          savePlannerSettings({
                            prefer_discounts_and_save_food: e.target.checked,
                          })
                        }
                        className="w-4 h-4 accent-emerald-500"
                      />
                    </label>
                  </div>

                  {/* Allergén tiltólista */}
                  <div className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-3.5 space-y-2">
                    <div className="text-xs font-bold text-slate-700 dark:text-slate-300">
                      🚫 Allergén / Diéta szűrő
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {["laktóz", "glutén", "diófélék", "tojás", "szója", "hal"].map((al) => {
                        const active = plannerSettings.allergens.includes(al);
                        return (
                          <button
                            type="button"
                            key={al}
                            onClick={() => {
                              const next = active
                                ? plannerSettings.allergens.filter((x) => x !== al)
                                : [...plannerSettings.allergens, al];
                              savePlannerSettings({ allergens: next });
                            }}
                            className={`px-2.5 py-1 rounded-xl text-[11px] font-bold border transition ${
                              active
                                ? "bg-rose-500 text-white border-rose-500"
                                : "bg-white dark:bg-[#1C2218] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
                            }`}
                          >
                            {active ? `✕ ${al}` : al}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* ✨ AI Random Új Receptajánlás vezérlő (Ki/Be, Hány db, Melyik étkezésben) */}
                <div className="rounded-2xl bg-slate-50 dark:bg-[#121510] border border-slate-200/80 dark:border-white/10 p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <label className="flex items-center gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={plannerSettings.ai_recommendations_enabled}
                      onChange={(e) =>
                        savePlannerSettings({ ai_recommendations_enabled: e.target.checked })
                      }
                      className="w-5 h-5 accent-emerald-500 shrink-0"
                    />
                    <div>
                      <div className="text-xs sm:text-sm font-bold text-slate-900 dark:text-white">
                        ✨ AI új receptajánlások a heti menüben (Ki / Be)
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400">
                        {plannerSettings.ai_recommendations_enabled
                          ? "A heti menü generáláskor a saját receptjeid mellé betesz új AI ötleteket is."
                          : "Kikapcsolva: a heti menü 100%-ban csak a saját elmentett receptjeidből készül!"}
                      </div>
                    </div>
                  </label>

                  {plannerSettings.ai_recommendations_enabled && (
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                          Mennyi?
                        </span>
                        {[1, 2, 3, 4, 5].map((cnt) => {
                          const active = plannerSettings.ai_recommendation_count === cnt;
                          return (
                            <button
                              type="button"
                              key={cnt}
                              onClick={() => savePlannerSettings({ ai_recommendation_count: cnt })}
                              className={`w-8 h-8 rounded-xl text-xs font-bold border transition ${
                                active
                                  ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                                  : "bg-white dark:bg-[#1C2218] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10"
                              }`}
                            >
                              {cnt}
                            </button>
                          );
                        })}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
                          Miben?
                        </span>
                        {(
                          [
                            { id: "reggeli", l: "🌅 Reggeli" },
                            { id: "ebed", l: "🍲 Ebéd" },
                            { id: "vacsora", l: "🌙 Vacsora" },
                          ] as const
                        ).map((m) => {
                          const meals = plannerSettings.ai_recommendation_meals || ["ebed"];
                          const active = meals.includes(m.id);
                          return (
                            <button
                              type="button"
                              key={m.id}
                              onClick={() => {
                                const next = active
                                  ? meals.filter((x) => x !== m.id)
                                  : [...meals, m.id];
                                if (next.length > 0) {
                                  savePlannerSettings({ ai_recommendation_meals: next });
                                }
                              }}
                              className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition ${
                                active
                                  ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                                  : "bg-white dark:bg-[#1C2218] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
                              }`}
                            >
                              {m.l}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* 5. Kártya: 🤖 SAJÁT AI API KULCS (BYOK — Multi-User) */}
              <div className="lg:col-span-3 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/80 dark:border-white/5 p-5 sm:p-6 space-y-4 shadow-sm dark:shadow-none">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <KeyRound className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                    <div>
                      <h3 className="font-bold text-base text-slate-900 dark:text-white">
                        🤖 Saját AI API Kulcs (BYOK — Gemini / OpenAI / Ollama)
                      </h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Ha megadod a saját API kulcsodat (AES titkosítva tároljuk!), korlátlanul és saját keretedből használhatod az AI séfet (~30–150 Ft/hó).
                      </p>
                    </div>
                  </div>
                  <span
                    className={`text-xs font-bold px-3 py-1 rounded-full ${
                      currentUser?.llm.using_own_key
                        ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                        : "bg-slate-100 dark:bg-white/10 text-slate-600 dark:text-slate-300"
                    }`}
                  >
                    {currentUser?.llm.using_own_key
                      ? `✅ Saját kulcs aktív (${currentUser.llm.masked_api_key})`
                      : status?.ai_daily_limit
                      ? `Szerver keret (${status.ai_daily_used || 0}/${status.ai_daily_limit}/nap)`
                      : "Szerver kulcs aktív"}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 mb-1">
                      Szolgáltató
                    </label>
                    <select
                      value={byokProvider}
                      onChange={(e) => {
                        const p = e.target.value;
                        setByokProvider(p);
                        if (p === "gemini") setByokModel("gemini-3.1-flash-lite");
                        else if (p === "openai") setByokModel("gpt-4.1-mini");
                        else setByokModel("qwen2.5:14b");
                      }}
                      className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-xl px-3 py-2.5 text-xs border border-slate-200 dark:border-white/10"
                    >
                      <option value="gemini">Google Gemini API</option>
                      <option value="openai">OpenAI API</option>
                      <option value="custom">Saját / Ollama (OpenAI-komp.)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-slate-500 mb-1">Modell</label>
                    <input
                      type="text"
                      value={byokModel}
                      onChange={(e) => setByokModel(e.target.value)}
                      placeholder="pl. gemini-3.1-flash-lite vagy gpt-4.1-mini"
                      className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-xl px-3 py-2.5 text-xs border border-slate-200 dark:border-white/10"
                    />
                  </div>

                  <div className="md:col-span-2">
                    <label className="block text-[11px] font-bold text-slate-500 mb-1">
                      Saját API Kulcs {currentUser?.llm.masked_api_key ? `(mentve: ${currentUser.llm.masked_api_key})` : ""}
                    </label>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        value={byokApiKey}
                        onChange={(e) => setByokApiKey(e.target.value)}
                        placeholder="AIzaSy... vagy sk-..."
                        className="flex-1 bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-xl px-3 py-2.5 text-xs border border-slate-200 dark:border-white/10"
                      />
                      <button
                        type="button"
                        disabled={busyAction === "byok"}
                        onClick={() => handleSaveByok(false)}
                        className="px-4 py-2 rounded-xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs shrink-0"
                      >
                        Mentés
                      </button>
                      {currentUser?.llm.using_own_key && (
                        <button
                          type="button"
                          disabled={busyAction === "byok"}
                          onClick={() => handleSaveByok(true)}
                          className="px-3 py-2 rounded-xl bg-rose-500/15 text-rose-600 dark:text-rose-300 font-bold text-xs shrink-0"
                        >
                          Törlés
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* 6. Kártya (Teljes szélességű): SAJÁT KIFLI OTTHON MCP SZERVER CLAUDE-HOZ */}
              <div className="lg:col-span-3 rounded-3xl bg-white dark:bg-[#1C2218] border border-emerald-500/30 p-5 sm:p-6 space-y-4 shadow-sm dark:shadow-none">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <Terminal className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
                    <div>
                      <h3 className="font-bold text-base text-slate-900 dark:text-white">
                        🔌 Saját „Kifli Otthon” MCP Szerver (Claude mobil app / Desktop / Code)
                      </h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Személyes, csak a te fiókodhoz tartozó MCP végpontod — másold be a Claude Custom Connectorba!
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono font-bold px-3 py-1.5 rounded-xl bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 break-all">
                      {personalMcpPath}
                    </span>
                    {currentUser && !currentUser.is_demo && (
                      <button
                        type="button"
                        onClick={async () => {
                          const u = await apiFetch<UserProfile>("/api/auth/mcp-token/rotate", {
                            method: "POST",
                          });
                          setCurrentUser(u);
                          notify("🔑 Új személyes MCP kulcs generálva!");
                        }}
                        className="px-2.5 py-1.5 rounded-xl bg-slate-100 dark:bg-white/10 text-xs font-semibold text-slate-600 dark:text-slate-300"
                      >
                        Új kulcs
                      </button>
                    )}
                  </div>
                </div>

                <div className="relative">
                  <pre className="rounded-2xl bg-slate-900 dark:bg-[#121510] text-emerald-300 text-xs p-4 overflow-x-auto border border-slate-800 dark:border-white/10 leading-relaxed">
{JSON.stringify(
  {
    mcpServers: {
      "kifli-otthon": {
        command: "npx",
        args: ["-y", "mcp-remote", personalMcpPath, "--allow-http"],
      },
    },
  },
  null,
  2
)}
                  </pre>
                  <button
                    type="button"
                    onClick={() => {
                      navigator.clipboard.writeText(personalMcpPath);
                      notify("📋 Személyes MCP URL a vágólapra másolva!");
                    }}
                    className="absolute top-3 right-3 px-3 py-1.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs flex items-center gap-1.5 shadow"
                  >
                    <Copy className="w-3.5 h-3.5" /> URL Másolása
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* =====================================================================
          MOBIL STICKY BOTTOM TAB BAR (Light + Dark, iOS safe-area!)
         ===================================================================== */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-40 bg-white/95 dark:bg-[#151912]/95 backdrop-blur-2xl border-t border-slate-200 dark:border-white/10 pb-safe">
        <div className="grid grid-cols-6 px-1 pt-1.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`relative flex flex-col items-center justify-center py-1.5 rounded-xl transition ${
                  active
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-slate-500 dark:text-slate-400"
                }`}
              >
                <div className="relative">
                  <Icon className={`w-5 h-5 ${active ? "scale-110" : ""} transition-transform`} />
                  {item.badge !== undefined && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 rounded-full bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 text-[10px] font-black flex items-center justify-center">
                      {item.badge}
                    </span>
                  )}
                </div>
                <span className="text-[10px] font-semibold mt-1 tracking-tight">{item.label}</span>
              </button>
            );
          })}
        </div>
      </nav>

      {/* MODAL: ⭐ KEDVELT TERMÉKEK -> KIFLI SAJÁTMÁRKA CSERE POPUP */}
      {favoriteSwapModal && (
        <PrivateLabelSwapModal
          autoSwappedCount={favoriteSwapModal.autoSwappedCount}
          autoSavingsFt={favoriteSwapModal.autoSavingsFt}
          proposals={favoriteSwapModal.proposals}
          busy={busyAction === "apply-fav-swaps"}
          onClose={() => setFavoriteSwapModal(null)}
          onSwapOne={(proposal) => handleApplyFavoriteSwaps([proposal])}
          onSwapAll={(remaining) => handleApplyFavoriteSwaps(remaining)}
        />
      )}

      {/* MODAL: 🔥 KAJA TINDER (Swipe jobbra/balra 0 AI tokennel!) */}
      {tinderOpen && (
        <FoodTinderSheet
          initialDay={tinderOpen.day}
          initialMealType={tinderOpen.mealType}
          recipes={recipes}
          onClose={() => setTinderOpen(null)}
          onAcceptRecipe={async (days, mealType, recipe) => {
            await handleManualSlotSwap(days, mealType, { recipeId: recipe.id });
          }}
        />
      )}

      {/* MODAL: 0 AI-TOKENES ÉTKEZÉS-CSERE SAJÁT RECEPTEKBŐL */}
      {swapTarget && (
        <MealSwapSheet
          initialDay={swapTarget.day}
          mealType={swapTarget.mealType}
          currentTitle={swapTarget.currentTitle}
          recipes={recipes}
          busy={busyAction === "manual-swap"}
          onClose={() => setSwapTarget(null)}
          onSelectRecipe={(days, mType, recipeId) =>
            handleManualSlotSwap(days, mType, { recipeId })
          }
          onSelectCustomTitle={(days, mType, customTitle) =>
            handleManualSlotSwap(days, mType, { customTitle })
          }
          onClearSlot={(days, mType) =>
            handleManualSlotSwap(days, mType, { clear: true })
          }
          onAskAiInstead={(dayLabel, mealLabel) => {
            setSwapTarget(null);
            setChatInput(`${dayLabel} ${mealLabel.toLowerCase()}re inkább `);
            setActiveTab("chat");
          }}
        />
      )}

      {/* MODAL / BOTTOM SHEET: ÚJ VAGY MEGLÉVŐ RECEPT SZERKESZTÉSE */}
      {showNewRecipeSheet && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 dark:bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
          <form
            onSubmit={handleSaveRecipe}
            className="w-full max-w-lg max-h-[92dvh] overflow-y-auto rounded-t-3xl sm:rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/10 p-5 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-slate-900 dark:text-white">
                {editingRecipeId !== null ? "✏️ Recept szerkesztése" : "🍲 Új recept hozzáadása"}
              </h3>
              <button
                type="button"
                onClick={() => {
                  setShowNewRecipeSheet(false);
                  setEditingRecipeId(null);
                }}
                className="p-1.5 rounded-full bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <input
              type="text"
              value={recTitle}
              onChange={(e) => setRecTitle(e.target.value)}
              placeholder="Recept neve (pl. Tárkonyos csirkeraguleves)"
              className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10"
              required
            />

            {/* Képfeltöltés + előnézet */}
            <div className="rounded-2xl bg-slate-50 dark:bg-[#121510]/70 border border-slate-200 dark:border-white/10 p-3 flex items-center gap-3">
              {pendingImagePreview || recImageUrl ? (
                <img
                  src={pendingImagePreview || recImageUrl}
                  alt="Recept kép"
                  className="w-16 h-16 rounded-xl object-cover shrink-0 border border-slate-200 dark:border-white/10"
                />
              ) : (
                <div className="w-16 h-16 rounded-xl bg-slate-200/70 dark:bg-white/5 flex items-center justify-center text-slate-400 shrink-0">
                  <ImagePlus className="w-6 h-6" />
                </div>
              )}
              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  📸 Recept fotója (Kaja Tinderhez és kártyákhoz)
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <label className="cursor-pointer px-3 py-1.5 rounded-xl bg-emerald-600/15 text-emerald-700 dark:text-emerald-300 text-xs font-bold border border-emerald-500/30 hover:bg-emerald-600/25 transition">
                    Kép választása
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) {
                          setPendingImageFile(file);
                          setPendingImagePreview(URL.createObjectURL(file));
                        }
                      }}
                    />
                  </label>
                  {(pendingImagePreview || recImageUrl) && (
                    <button
                      type="button"
                      onClick={() => {
                        setPendingImageFile(null);
                        setPendingImagePreview("");
                        setRecImageUrl("");
                      }}
                      className="text-xs text-rose-500 hover:underline"
                    >
                      Kép eltávolítása
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Healthy Score 1–5 választó */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-slate-700 dark:text-slate-300">
                  💚 Healthy Score (heti menü egyensúlyhoz)
                </span>
                <span className="font-bold text-emerald-600 dark:text-emerald-400">
                  {HEALTHY_META[recHealthyScore]?.emoji} {recHealthyScore}/5 ·{" "}
                  {HEALTHY_META[recHealthyScore]?.label}
                </span>
              </div>
              <div className="grid grid-cols-5 gap-1.5">
                {[1, 2, 3, 4, 5].map((score) => {
                  const meta = HEALTHY_META[score];
                  const active = recHealthyScore === score;
                  return (
                    <button
                      type="button"
                      key={score}
                      onClick={() => setRecHealthyScore(score)}
                      className={`py-2 rounded-xl text-xs font-bold border transition flex flex-col items-center gap-0.5 ${
                        active
                          ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500 shadow-sm"
                          : "bg-slate-100 dark:bg-[#121510] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
                      }`}
                    >
                      <span className="text-sm leading-none">{meta.emoji}</span>
                      <span>{score}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="flex gap-1.5">
                {[
                  { id: "reggeli", l: "Reggeli" },
                  { id: "ebed", l: "Ebéd" },
                  { id: "vacsora", l: "Vacsora" },
                ].map((c) => {
                  const sel = recCats.includes(c.id);
                  return (
                    <button
                      type="button"
                      key={c.id}
                      onClick={() =>
                        setRecCats((prev) =>
                          sel ? prev.filter((x) => x !== c.id) : [...prev, c.id]
                        )
                      }
                      className={`px-3 py-1.5 rounded-xl text-xs font-bold border ${
                        sel
                          ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                          : "bg-slate-100 dark:bg-[#121510] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
                      }`}
                    >
                      {c.l}
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
                <span>Adag:</span>
                <input
                  type="number"
                  min={1}
                  value={recServings}
                  onChange={(e) => setRecServings(parseInt(e.target.value || "2", 10))}
                  className="w-14 bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white text-center rounded-xl py-1.5 border border-slate-200 dark:border-white/10"
                />
              </div>
            </div>

            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  Hozzávalók
                </span>
                <span className="text-[11px] text-slate-500">🧂 = kamrában van (nem rendeli)</span>
              </div>
              {recIngs.map((ing, idx) => (
                <div
                  key={idx}
                  className="rounded-2xl bg-slate-50 dark:bg-[#121510]/70 border border-slate-200 dark:border-white/5 p-2 space-y-1.5"
                >
                  <div className="grid grid-cols-12 gap-1.5 items-center">
                    <input
                      type="text"
                      value={ing.name}
                      onChange={(e) => {
                        const copy = [...recIngs];
                        copy[idx] = { ...copy[idx], name: e.target.value };
                        setRecIngs(copy);
                      }}
                      placeholder="Alapanyag"
                      className="col-span-5 bg-white dark:bg-[#121510] text-slate-900 dark:text-white rounded-xl px-2.5 py-2 text-xs border border-slate-200 dark:border-white/10"
                    />
                    <input
                      type="number"
                      step="0.1"
                      value={ing.quantity}
                      onChange={(e) => {
                        const copy = [...recIngs];
                        copy[idx] = { ...copy[idx], quantity: parseFloat(e.target.value || "1") };
                        setRecIngs(copy);
                      }}
                      className="col-span-2 bg-white dark:bg-[#121510] text-slate-900 dark:text-white text-center rounded-xl px-1 py-2 text-xs border border-slate-200 dark:border-white/10"
                    />
                    <input
                      type="text"
                      value={ing.unit}
                      onChange={(e) => {
                        const copy = [...recIngs];
                        copy[idx] = { ...copy[idx], unit: e.target.value };
                        setRecIngs(copy);
                      }}
                      placeholder="g/db"
                      className="col-span-3 bg-white dark:bg-[#121510] text-slate-900 dark:text-white text-center rounded-xl px-1 py-2 text-xs border border-slate-200 dark:border-white/10"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        const copy = [...recIngs];
                        copy[idx] = { ...copy[idx], is_staple: !copy[idx].is_staple };
                        setRecIngs(copy);
                      }}
                      title="Kamra-alapanyag kapcsoló"
                      className={`col-span-1 h-8 rounded-lg text-xs flex items-center justify-center border ${
                        ing.is_staple
                          ? "bg-amber-500/20 border-amber-400/40 text-amber-700 dark:text-amber-300"
                          : "bg-white dark:bg-white/5 border-slate-200 dark:border-white/5 text-slate-500"
                      }`}
                    >
                      🧂
                    </button>
                    <button
                      type="button"
                      onClick={() => setRecIngs(recIngs.filter((_, i) => i !== idx))}
                      className="col-span-1 text-slate-400 hover:text-rose-500 flex justify-center"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                  <input
                    type="text"
                    value={ing.brand_hint || ""}
                    onChange={(e) => {
                      const copy = [...recIngs];
                      copy[idx] = { ...copy[idx], brand_hint: e.target.value };
                      setRecIngs(copy);
                    }}
                    placeholder="Opcionális márka / megjegyzés (pl. Barilla, laktózmentes...)"
                    className="w-full bg-white dark:bg-[#121510] rounded-xl px-2.5 py-1.5 text-[11px] text-slate-700 dark:text-slate-300 placeholder-slate-400 dark:placeholder-slate-600 border border-slate-200 dark:border-white/5"
                  />
                </div>
              ))}
              <button
                type="button"
                onClick={() =>
                  setRecIngs([
                    ...recIngs,
                    { name: "", quantity: 1, unit: "g", brand_hint: "", is_staple: false },
                  ])
                }
                className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1 pt-1"
              >
                <Plus className="w-3.5 h-3.5" /> Hozzávaló hozzáadása
              </button>
            </div>

            <textarea
              rows={2}
              value={recInstructions}
              onChange={(e) => setRecInstructions(e.target.value)}
              placeholder="Rövid megjegyzés / elkészítés (opcionális)"
              className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-3.5 py-2.5 text-xs border border-slate-200 dark:border-white/10"
            />

            <button
              type="submit"
              disabled={busyAction === "save-recipe"}
              className="w-full py-3 rounded-2xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-sm shadow-md"
            >
              {editingRecipeId !== null ? "Módosítások mentése" : "Recept mentése"}
            </button>
          </form>
        </div>
      )}

      {/* MODAL / BOTTOM SHEET: AI RECEPT IMPORT */}
      {showImportSheet && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 dark:bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
          <form
            onSubmit={handleImportRecipe}
            className="w-full max-w-lg rounded-t-3xl sm:rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/10 p-5 space-y-4 shadow-2xl"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-base text-slate-900 dark:text-white">
                ⚡ AI Recept Importálás
              </h3>
              <button
                type="button"
                onClick={() => setShowImportSheet(false)}
                className="p-1.5 rounded-full bg-slate-100 dark:bg-white/5 text-slate-500 dark:text-slate-400"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Illessz be egy recept linket (pl. StreetKitchen, Nosalty) vagy másold be nyersen a hozzávalókat — az AI automatikusan szétszedi és elmenti!
            </p>
            <textarea
              rows={4}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder="https://... vagy nyers recept szöveg"
              className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10"
              required
            />
            <button
              type="submit"
              disabled={busyAction === "import-recipe"}
              className="w-full py-3 rounded-2xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-sm shadow-md"
            >
              {busyAction === "import-recipe" ? "⏳ Kinyerés folyamatban..." : "Kinyerés és Mentés"}
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
