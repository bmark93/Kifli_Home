import React, { useMemo, useState } from "react";
import { Search, X, Check, Trash2, MessageSquareText, UtensilsCrossed } from "lucide-react";
import { type Recipe } from "./api";

const DAYS_LIST = [
  { key: "hetfo", short: "H", label: "Hétfő" },
  { key: "kedd", short: "K", label: "Kedd" },
  { key: "szerda", short: "Sze", label: "Szerda" },
  { key: "csutortok", short: "Cs", label: "Csütörtök" },
  { key: "pentek", short: "P", label: "Péntek" },
  { key: "szombat", short: "Szo", label: "Szombat" },
  { key: "vasarnap", short: "V", label: "Vasárnap" },
];

const MEAL_LABELS: Record<string, string> = {
  reggeli: "🌅 Reggeli",
  ebed: "🍲 Ebéd",
  vacsora: "🌙 Vacsora",
};

interface Props {
  initialDay: string;
  mealType: "reggeli" | "ebed" | "vacsora";
  currentTitle?: string;
  recipes: Recipe[];
  busy: boolean;
  onClose: () => void;
  onSelectRecipe: (days: string[], mealType: string, recipeId: number) => Promise<void>;
  onSelectCustomTitle: (days: string[], mealType: string, title: string) => Promise<void>;
  onClearSlot: (days: string[], mealType: string) => Promise<void>;
  onAskAiInstead: (dayLabel: string, mealLabel: string) => void;
}

export function MealSwapSheet({
  initialDay,
  mealType,
  currentTitle,
  recipes,
  busy,
  onClose,
  onSelectRecipe,
  onSelectCustomTitle,
  onClearSlot,
  onAskAiInstead,
}: Props) {
  const [selectedDays, setSelectedDays] = useState<string[]>([initialDay]);
  const [onlyMatchingCategory, setOnlyMatchingCategory] = useState<boolean>(true);
  const [search, setSearch] = useState<string>("");
  const [customTitle, setCustomTitle] = useState<string>("");

  const dayLabel = DAYS_LIST.find((d) => d.key === initialDay)?.label || initialDay;

  function toggleDay(dk: string) {
    setSelectedDays((prev) => {
      if (prev.includes(dk)) {
        return prev.length > 1 ? prev.filter((x) => x !== dk) : prev;
      }
      return [...prev, dk];
    });
  }

  const visibleRecipes = useMemo(() => {
    const q = search.trim().toLowerCase();
    return recipes.filter((r) => {
      if (onlyMatchingCategory && !r.categories.includes(mealType)) return false;
      if (q && !r.title.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [recipes, onlyMatchingCategory, mealType, search]);

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 dark:bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="w-full max-w-2xl max-h-[92dvh] flex flex-col rounded-t-3xl sm:rounded-3xl bg-white dark:bg-[#11192a] border border-slate-200 dark:border-white/10 shadow-2xl overflow-hidden">
        {/* Fejléc */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-white/10 flex items-center justify-between bg-slate-50 dark:bg-[#141e33]">
          <div>
            <div className="text-xs font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider">
              ⚡ Azonnali csere (0 AI token)
            </div>
            <h3 className="font-bold text-base text-slate-900 dark:text-white mt-0.5">
              {dayLabel} · {MEAL_LABELS[mealType]}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full bg-slate-200/70 dark:bg-white/10 text-slate-600 dark:text-slate-300 hover:opacity-80"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Napok többes kijelölése (pl. Hétfő + Kedd egyszerre!) */}
        <div className="px-5 py-3 border-b border-slate-200 dark:border-white/10 bg-slate-50/60 dark:bg-[#0d1424] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
              Melyik napokra állítsam be egyszerre? (pl. 2 napos főzés)
            </span>
          </div>
          <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
            {DAYS_LIST.map((d) => {
              const active = selectedDays.includes(d.key);
              return (
                <button
                  type="button"
                  key={d.key}
                  onClick={() => toggleDay(d.key)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold border transition flex items-center gap-1 ${
                    active
                      ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500 shadow-sm"
                      : "bg-white dark:bg-[#11192a] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10"
                  }`}
                >
                  {active && <Check className="w-3 h-3" />}
                  <span>{d.short}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Kereső + Kategória szűrő */}
        <div className="px-5 pt-3 pb-2 flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Keresés a saját receptjeid között..."
              className="w-full pl-9 pr-3 py-2.5 rounded-2xl text-sm bg-slate-100 dark:bg-[#090d16] text-slate-900 dark:text-white border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
            />
          </div>

          <div className="flex gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => setOnlyMatchingCategory(true)}
              className={`px-3 py-2 rounded-2xl text-xs font-bold border transition ${
                onlyMatchingCategory
                  ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                  : "bg-slate-100 dark:bg-[#090d16] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10"
              }`}
            >
              Csak {MEAL_LABELS[mealType].split(" ")[1]}
            </button>
            <button
              type="button"
              onClick={() => setOnlyMatchingCategory(false)}
              className={`px-3 py-2 rounded-2xl text-xs font-bold border transition ${
                !onlyMatchingCategory
                  ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                  : "bg-slate-100 dark:bg-[#090d16] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10"
              }`}
            >
              Összes ({recipes.length})
            </button>
          </div>
        </div>

        {/* Receptek görgethető listája */}
        <div className="flex-1 overflow-y-auto px-5 py-2 space-y-2">
          {visibleRecipes.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500 dark:text-slate-400 space-y-2">
              <UtensilsCrossed className="w-8 h-8 mx-auto opacity-50" />
              <p>Nincs találat ebben a kategóriában.</p>
              {onlyMatchingCategory && (
                <button
                  type="button"
                  onClick={() => setOnlyMatchingCategory(false)}
                  className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 underline"
                >
                  Mutasd az összes receptet
                </button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {visibleRecipes.map((r) => {
                const isCurrent = currentTitle === r.title;
                return (
                  <button
                    type="button"
                    disabled={busy}
                    key={r.id}
                    onClick={() => onSelectRecipe(selectedDays, mealType, r.id)}
                    className={`text-left rounded-2xl p-3.5 border transition active:scale-[0.99] ${
                      isCurrent
                        ? "bg-emerald-50 dark:bg-emerald-500/15 border-emerald-500/50"
                        : "bg-slate-50 hover:bg-emerald-50/60 dark:bg-[#090d16] dark:hover:bg-white/5 border-slate-200 dark:border-white/10"
                    }`}
                  >
                    <div className="font-bold text-sm text-slate-900 dark:text-white leading-snug">
                      {r.title}
                    </div>
                    <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                      {r.ingredients.map((i) => i.name).join(", ")}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Lábléc: Gyors egyedi felirat / Üresre törlés / AI Chat link */}
        <div className="px-5 py-3.5 border-t border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-[#141e33] space-y-2.5">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (customTitle.trim()) {
                onSelectCustomTitle(selectedDays, mealType, customTitle.trim());
              }
            }}
            className="flex gap-2"
          >
            <input
              type="text"
              value={customTitle}
              onChange={(e) => setCustomTitle(e.target.value)}
              placeholder="Vagy szabad szöveg (pl. Rendelés / Étterem / Maradék)..."
              className="flex-1 rounded-xl px-3 py-2 text-xs bg-white dark:bg-[#090d16] text-slate-900 dark:text-white border border-slate-200 dark:border-white/10"
            />
            <button
              type="submit"
              disabled={!customTitle.trim() || busy}
              className="px-3.5 py-2 rounded-xl bg-slate-800 dark:bg-white/15 text-white text-xs font-semibold disabled:opacity-40"
            >
              Beír
            </button>
          </form>

          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              type="button"
              disabled={busy}
              onClick={() => onClearSlot(selectedDays, mealType)}
              className="text-xs font-semibold text-rose-600 dark:text-rose-400 hover:underline flex items-center gap-1"
            >
              <Trash2 className="w-3.5 h-3.5" /> Étkezés kihagyása / törlése
            </button>

            <button
              type="button"
              onClick={() => onAskAiInstead(dayLabel, MEAL_LABELS[mealType].split(" ")[1])}
              className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 hover:underline flex items-center gap-1"
            >
              <MessageSquareText className="w-3.5 h-3.5" /> Új ötlet kérése AI chatben →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
