import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  X,
  Heart,
  RotateCcw,
  Flame,
  Check,
  UtensilsCrossed,
  Sparkles,
  Sunrise,
  Sun,
  Moon,
} from "lucide-react";
import { HEALTHY_META, type Recipe } from "./api";

const DAYS_LIST = [
  { key: "hetfo", short: "H", label: "Hétfő" },
  { key: "kedd", short: "K", label: "Kedd" },
  { key: "szerda", short: "Sze", label: "Szerda" },
  { key: "csutortok", short: "Cs", label: "Csütörtök" },
  { key: "pentek", short: "P", label: "Péntek" },
  { key: "szombat", short: "Szo", label: "Szombat" },
  { key: "vasarnap", short: "V", label: "Vasárnap" },
];

type MealType = "reggeli" | "ebed" | "vacsora";

interface Props {
  initialDay: string;
  initialMealType?: MealType;
  recipes: Recipe[];
  onClose: () => void;
  onAcceptRecipe: (days: string[], mealType: MealType, recipe: Recipe) => Promise<void>;
}

function shuffle<T>(arr: T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export function FoodTinderSheet({
  initialDay,
  initialMealType = "ebed",
  recipes,
  onClose,
  onAcceptRecipe,
}: Props) {
  const [mealType, setMealType] = useState<MealType>(initialMealType);
  const [selectedDays, setSelectedDays] = useState<string[]>([initialDay]);
  const [healthyOnly, setHealthyOnly] = useState<boolean>(false);
  const [deckSeed, setDeckSeed] = useState<number>(0);
  const [index, setIndex] = useState<number>(0);
  const [lastPicked, setLastPicked] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);

  // Drag / Swipe fizika
  const [dragX, setDragX] = useState<number>(0);
  const [dragY, setDragY] = useState<number>(0);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [flyDir, setFlyDir] = useState<"left" | "right" | null>(null);
  const startPos = useRef<{ x: number; y: number } | null>(null);

  const deck = useMemo(() => {
    const filtered = recipes.filter((r) => {
      if (!r.categories.includes(mealType)) return false;
      if (healthyOnly && (r.healthy_score || 3) < 4) return false;
      return true;
    });
    return shuffle(filtered);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipes, mealType, healthyOnly, deckSeed]);

  useEffect(() => {
    setIndex(0);
    setDragX(0);
    setDragY(0);
    setFlyDir(null);
  }, [mealType, healthyOnly, deckSeed]);

  const current = deck[index] || null;
  const nextCard = deck[index + 1] || null;

  function toggleDay(dk: string) {
    setSelectedDays((prev) => {
      if (prev.includes(dk)) {
        return prev.length > 1 ? prev.filter((x) => x !== dk) : prev;
      }
      return [...prev, dk];
    });
  }

  async function triggerSwipe(dir: "left" | "right") {
    if (!current || saving || flyDir) return;
    setFlyDir(dir);
    setDragX(dir === "right" ? 420 : -420);

    if (dir === "right") {
      setSaving(true);
      try {
        await onAcceptRecipe(selectedDays, mealType, current);
        const dayNames = selectedDays
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.short || dk)
          .join("+");
        setLastPicked(`✅ ${current.title} → ${dayNames}`);
      } finally {
        setSaving(false);
      }
    }

    setTimeout(() => {
      setFlyDir(null);
      setDragX(0);
      setDragY(0);
      setIndex((i) => i + 1);
    }, 220);
  }

  // Billentyűzet támogatás PC-n (← Balra: Pass, → Jobbra: Like)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") triggerSwipe("left");
      else if (e.key === "ArrowRight") triggerSwipe("right");
      else if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (saving || flyDir) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    startPos.current = { x: e.clientX, y: e.clientY };
    setIsDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!isDragging || !startPos.current) return;
    setDragX(e.clientX - startPos.current.x);
    setDragY((e.clientY - startPos.current.y) * 0.25);
  }

  function onPointerUp() {
    if (!isDragging) return;
    setIsDragging(false);
    startPos.current = null;
    if (dragX > 95) {
      triggerSwipe("right");
    } else if (dragX < -95) {
      triggerSwipe("left");
    } else {
      setDragX(0);
      setDragY(0);
    }
  }

  const hMeta = current ? HEALTHY_META[current.healthy_score || 3] || HEALTHY_META[3] : HEALTHY_META[3];
  const likeOpacity = Math.min(1, Math.max(0, (dragX - 25) / 85));
  const passOpacity = Math.min(1, Math.max(0, (-dragX - 25) / 85));

  const mealGradient =
    mealType === "reggeli"
      ? "from-amber-500 via-orange-500 to-rose-500"
      : mealType === "ebed"
      ? "from-emerald-500 via-teal-600 to-cyan-700"
      : "from-indigo-500 via-purple-600 to-slate-800";

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="w-full max-w-md max-h-[96dvh] flex flex-col rounded-t-3xl sm:rounded-3xl bg-white dark:bg-[#0f172a] border border-slate-200 dark:border-white/10 shadow-2xl overflow-hidden">
        {/* Fejléc */}
        <div className="px-4 py-3.5 border-b border-slate-200 dark:border-white/10 flex items-center justify-between bg-slate-50 dark:bg-[#141e33]">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-rose-500 to-orange-500 text-white flex items-center justify-center shadow">
              <Flame className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-black text-base text-slate-900 dark:text-white leading-none">
                Kaja Tinder
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                Húzd jobbra ha jöhet, balra ha passz! (0 AI token)
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full bg-slate-200/70 dark:bg-white/10 text-slate-600 dark:text-slate-300"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Kategória választó + Egészséges szűrő */}
        <div className="px-4 pt-3 pb-2 space-y-2.5 bg-slate-50/70 dark:bg-[#0c1322] border-b border-slate-200 dark:border-white/10">
          <div className="grid grid-cols-3 gap-1.5">
            {(
              [
                { id: "reggeli", label: "Reggeli", icon: Sunrise },
                { id: "ebed", label: "Ebéd", icon: Sun },
                { id: "vacsora", label: "Vacsora", icon: Moon },
              ] as const
            ).map((m) => {
              const Icon = m.icon;
              const active = mealType === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setMealType(m.id)}
                  className={`py-2 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 border transition ${
                    active
                      ? "bg-emerald-600 text-white border-emerald-600 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500 shadow-sm"
                      : "bg-white dark:bg-[#11192a] text-slate-600 dark:text-slate-300 border-slate-200 dark:border-white/10"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {m.label}
                </button>
              );
            })}
          </div>

          {/* Melyik nap(ok)ra */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex gap-1 overflow-x-auto no-scrollbar">
              {DAYS_LIST.map((d) => {
                const active = selectedDays.includes(d.key);
                return (
                  <button
                    type="button"
                    key={d.key}
                    onClick={() => toggleDay(d.key)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-bold border transition flex items-center gap-0.5 ${
                      active
                        ? "bg-rose-500 text-white border-rose-500 shadow-sm"
                        : "bg-white dark:bg-[#11192a] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
                    }`}
                  >
                    {active && <Check className="w-2.5 h-2.5" />}
                    {d.short}
                  </button>
                );
              })}
            </div>

            <button
              type="button"
              onClick={() => setHealthyOnly((v) => !v)}
              className={`shrink-0 px-2.5 py-1 rounded-lg text-[11px] font-bold border transition ${
                healthyOnly
                  ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300 border-emerald-500/40"
                  : "bg-white dark:bg-[#11192a] text-slate-500 border-slate-200 dark:border-white/10"
              }`}
              title="Csak 4-5 Healthy Score ételek"
            >
              💚 4-5
            </button>
          </div>
        </div>

        {/* Utolsó választás visszajelzés */}
        {lastPicked && (
          <div className="px-4 py-1.5 bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 text-xs font-semibold text-center border-b border-emerald-500/20">
            {lastPicked}
          </div>
        )}

        {/* SWIPE KÁRTYA TERÜLET */}
        <div className="relative flex-1 min-h-[380px] sm:min-h-[410px] p-4 flex items-center justify-center overflow-hidden select-none">
          {!current ? (
            <div className="text-center space-y-3 p-6">
              <Sparkles className="w-12 h-12 mx-auto text-emerald-500/60" />
              <div className="font-bold text-base text-slate-800 dark:text-white">
                {deck.length === 0
                  ? "Nincs recept ebben a kategóriában!"
                  : "Végigpörgetted az összes receptet!"}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {deck.length === 0
                  ? "Vegyél fel recepteket (vagy kapcsold ki a 💚 4-5 szűrőt)."
                  : "Keverd újra a paklit, vagy válassz másik kategóriát!"}
              </p>
              {deck.length > 0 && (
                <button
                  type="button"
                  onClick={() => setDeckSeed((s) => s + 1)}
                  className="px-5 py-2.5 rounded-2xl bg-emerald-600 text-white dark:bg-emerald-500 dark:text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow"
                >
                  <RotateCcw className="w-3.5 h-3.5" /> Pakli újrakeverése
                </button>
              )}
            </div>
          ) : (
            <div className="relative w-full h-[360px] sm:h-[385px]">
              {/* Hátsó (következő) kártya előnézet */}
              {nextCard && (
                <div className="absolute inset-0 rounded-3xl bg-slate-100 dark:bg-[#162036] border border-slate-200 dark:border-white/10 scale-[0.94] translate-y-3 opacity-60 pointer-events-none" />
              )}

              {/* Aktív húzható kártya */}
              <div
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                style={{
                  transform: `translate3d(${dragX}px, ${dragY}px, 0) rotate(${dragX * 0.045}deg)`,
                  transition: isDragging ? "none" : "transform 0.22s ease-out",
                  touchAction: "none",
                }}
                className="absolute inset-0 rounded-3xl bg-white dark:bg-[#131d31] border border-slate-200 dark:border-white/15 shadow-2xl overflow-hidden flex flex-col cursor-grab active:cursor-grabbing"
              >
                {/* Kép / Gradiens fejléc */}
                <div className="relative h-48 sm:h-52 w-full shrink-0 overflow-hidden">
                  {current.image_url ? (
                    <img
                      src={current.image_url}
                      alt={current.title}
                      draggable={false}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div
                      className={`w-full h-full bg-gradient-to-br ${mealGradient} flex items-center justify-center`}
                    >
                      <UtensilsCrossed className="w-16 h-16 text-white/30" />
                    </div>
                  )}

                  {/* Sötétítő átmenet alul */}
                  <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-black/80 via-black/35 to-transparent" />

                  {/* LIKE / PASS Pecsétek húzás közben */}
                  {likeOpacity > 0.05 && (
                    <div
                      style={{ opacity: likeOpacity }}
                      className="absolute top-4 left-4 px-3.5 py-1 rounded-xl border-4 border-emerald-400 text-emerald-300 font-black text-xl tracking-wider -rotate-12 bg-black/40 backdrop-blur-sm"
                    >
                      EZ LESZ! 💚
                    </div>
                  )}
                  {passOpacity > 0.05 && (
                    <div
                      style={{ opacity: passOpacity }}
                      className="absolute top-4 right-4 px-3.5 py-1 rounded-xl border-4 border-rose-400 text-rose-300 font-black text-xl tracking-wider rotate-12 bg-black/40 backdrop-blur-sm"
                    >
                      NEM MOST ❌
                    </div>
                  )}

                  {/* Healthy Score badge jobb felül */}
                  <div className="absolute top-3 right-3 px-2.5 py-1 rounded-full bg-black/60 backdrop-blur-md text-white text-xs font-bold border border-white/20">
                    {hMeta.emoji} {current.healthy_score || 3}/5 · {hMeta.label}
                  </div>

                  {/* Cím alul a képen */}
                  <div className="absolute bottom-3 left-4 right-4">
                    <h4 className="text-xl font-black text-white leading-tight drop-shadow">
                      {current.title}
                    </h4>
                    <div className="text-xs text-slate-200/90 mt-0.5">
                      {current.servings} adag · {index + 1} / {deck.length}
                    </div>
                  </div>
                </div>

                {/* Hozzávalók és leírás */}
                <div className="p-4 flex-1 overflow-y-auto space-y-2.5">
                  <div className="flex flex-wrap gap-1.5">
                    {current.ingredients.slice(0, 10).map((ing, i) => (
                      <span
                        key={i}
                        className="text-xs px-2.5 py-1 rounded-xl bg-slate-100 dark:bg-[#090d16] border border-slate-200 dark:border-white/10 text-slate-700 dark:text-slate-300"
                      >
                        {ing.name}{" "}
                        <span className="text-slate-400">
                          {ing.quantity} {ing.unit}
                        </span>
                      </span>
                    ))}
                  </div>
                  {current.instructions && (
                    <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                      {current.instructions}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Alsó Tinder Akciógombok */}
        <div className="px-6 py-4 border-t border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-[#141e33] flex items-center justify-center gap-5">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            className="w-11 h-11 rounded-full bg-white dark:bg-white/5 border border-slate-200 dark:border-white/10 text-amber-500 flex items-center justify-center shadow-sm disabled:opacity-30 active:scale-90 transition"
            title="Visszalépés"
          >
            <RotateCcw className="w-5 h-5" />
          </button>

          <button
            type="button"
            disabled={!current || saving}
            onClick={() => triggerSwipe("left")}
            className="w-16 h-16 rounded-full bg-white dark:bg-[#1a1320] border-2 border-rose-500/40 text-rose-500 hover:bg-rose-500 hover:text-white flex items-center justify-center shadow-lg active:scale-90 transition disabled:opacity-30"
            title="Nem most (Balra)"
          >
            <X className="w-8 h-8" />
          </button>

          <button
            type="button"
            disabled={!current || saving}
            onClick={() => triggerSwipe("right")}
            className="w-16 h-16 rounded-full bg-emerald-500 hover:bg-emerald-400 text-white dark:text-slate-950 flex items-center justify-center shadow-lg shadow-emerald-500/30 active:scale-90 transition disabled:opacity-30"
            title="Ez lesz az! (Jobbra)"
          >
            <Heart className="w-8 h-8 fill-current" />
          </button>
        </div>
      </div>
    </div>
  );
}
