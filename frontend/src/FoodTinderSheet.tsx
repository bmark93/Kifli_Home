import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  X,
  Heart,
  RotateCcw,
  Check,
  UtensilsCrossed,
  Sparkles,
  Sunrise,
  Sun,
  Moon,
  Users,
  User,
  Copy,
  PartyPopper,
  ChefHat,
  SlidersHorizontal,
} from "lucide-react";
import {
  apiFetch,
  HEALTHY_META,
  type Recipe,
  type TinderSessionState,
  type TinderSwipeResult,
} from "./api";

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
  planDays?: number;
  daysPerMeal?: number;
  recipes: Recipe[];
  onClose: () => void;
  onAcceptRecipe: (days: string[], mealType: MealType, recipe: Recipe) => Promise<void>;
  onRefreshAfterCoupleAccept?: () => Promise<void>;
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
  planDays = 7,
  daysPerMeal = 1,
  recipes,
  onClose,
  onAcceptRecipe,
  onRefreshAfterCoupleAccept,
}: Props) {
  const availableDays = useMemo(
    () => DAYS_LIST.slice(0, Math.max(1, Math.min(7, planDays))),
    [planDays]
  );

  const [mode, setMode] = useState<"solo" | "couple">("solo");
  const [mealType, setMealType] = useState<MealType>(initialMealType);
  const [selectedDays, setSelectedDays] = useState<string[]>(() => {
    const startIdx = Math.max(
      0,
      availableDays.findIndex((d) => d.key === initialDay)
    );
    const span = Math.max(1, Math.min(daysPerMeal, availableDays.length - startIdx));
    return availableDays.slice(startIdx, startIdx + span).map((d) => d.key);
  });
  const [healthyOnly, setHealthyOnly] = useState<boolean>(false);
  const [showFilters, setShowFilters] = useState<boolean>(false);
  const [deckSeed, setDeckSeed] = useState<number>(0);
  const [index, setIndex] = useState<number>(0);
  const [lastPicked, setLastPicked] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [copiedCode, setCopiedCode] = useState<boolean>(false);

  // Közös (Páros) szoba state
  const [coupleSession, setCoupleSession] = useState<TinderSessionState | null>(null);
  const [userSlot, setUserSlot] = useState<"p1" | "p2">("p1");
  const [joinCodeInput, setJoinCodeInput] = useState<string>("");
  const [coupleError, setCoupleError] = useState<string>("");
  const [celebrateMatch, setCelebrateMatch] = useState<Recipe | null>(null);
  const [completedBanner, setCompletedBanner] = useState<string>("");
  const seenMatchIds = useRef<Set<number>>(new Set());
  const seenAcceptedCount = useRef<number>(0);

  // 3D Swipe fizika
  const [dragX, setDragX] = useState<number>(0);
  const [dragY, setDragY] = useState<number>(0);
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [flyDir, setFlyDir] = useState<"left" | "right" | null>(null);
  const startPos = useRef<{ x: number; y: number } | null>(null);

  // KRITIKUS FIX: Páros módban MINDKÉT telefon a szoba közös `deck_recipes` pakliját húzza!
  const deck = useMemo(() => {
    if (mode === "couple" && coupleSession?.deck_recipes) {
      return coupleSession.deck_recipes.filter((r) =>
        healthyOnly ? (r.healthy_score || 3) >= 4 : true
      );
    }
    const filtered = recipes.filter((r) => {
      if (!r.categories.includes(mealType)) return false;
      if (healthyOnly && (r.healthy_score || 3) < 4) return false;
      return true;
    });
    return shuffle(filtered);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipes, mealType, healthyOnly, deckSeed, mode, coupleSession?.code, coupleSession?.deck_recipes?.length]);

  useEffect(() => {
    setIndex(0);
    setDragX(0);
    setDragY(0);
    setFlyDir(null);
  }, [mealType, healthyOnly, deckSeed, mode, coupleSession?.code]);

  // Élő szinkronizálás (2 mp) a 2 telefon között (napok + elfogadott közös találatok + befejezés)
  useEffect(() => {
    if (mode !== "couple" || !coupleSession?.code) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await apiFetch<TinderSessionState>(
          `/api/tinder/sessions/${coupleSession.code}`
        );
        setCoupleSession(fresh);
        if (fresh.target_days && fresh.target_days.length) {
          setSelectedDays(fresh.target_days);
        }
        const accepted = fresh.accepted_matches || [];
        const acceptedIds = new Set(accepted.map((a) => a.recipe_id));

        if (accepted.length > seenAcceptedCount.current) {
          seenAcceptedCount.current = accepted.length;
          const newest = accepted[accepted.length - 1];
          if (newest) {
            const dNames = newest.days
              .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.short || dk)
              .join("+");
            setLastPicked(`💚 Szinkronizálva: ${newest.title} (${dNames})`);
          }
          if (onRefreshAfterCoupleAccept) {
            await onRefreshAfterCoupleAccept();
          }
        }

        // Ha a párod már betette a jelenleg ünnepelt ételt, csukjuk be a modált
        setCelebrateMatch((prev) => (prev && acceptedIds.has(prev.id) ? null : prev));

        if (fresh.is_completed && !completedBanner) {
          const mealWord = mealType === "reggeli" ? "reggeli" : mealType === "ebed" ? "ebéd" : "vacsora";
          setCelebrateMatch(null);
          setCompletedBanner(`Megvan a hétre a közös ${mealWord}!`);
          setTimeout(() => onClose(), 1800);
          return;
        }

        for (const m of fresh.matches) {
          if (!seenMatchIds.current.has(m.id) && !acceptedIds.has(m.id)) {
            seenMatchIds.current.add(m.id);
            setCelebrateMatch(m);
            break;
          }
        }
      } catch {
        // silent
      }
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, coupleSession?.code, completedBanner, mealType]);

  const current = deck[index] || null;
  const nextCard = deck[index + 1] || null;
  const thirdCard = deck[index + 2] || null;

  function triggerWeekCompleted(chosenMealType: MealType, extraNote?: string) {
    const mealWord =
      chosenMealType === "reggeli"
        ? "reggeli"
        : chosenMealType === "ebed"
        ? "ebéd"
        : "vacsora";
    setCelebrateMatch(null);
    setCompletedBanner(
      extraNote || `Megvan a hétre a(z) ${mealWord}!`
    );
    setTimeout(() => {
      onClose();
    }, 1800);
  }

  function isFinalStepOfWeek(chosenDays: string[]): boolean {
    if (!availableDays.length) return true;
    // Ha minden elérhető nap ki volt választva (pl. H-V), vagy elértük az utolsó napot (pl. Vasárnap)
    if (chosenDays.length >= availableDays.length) return true;
    const indices = chosenDays
      .map((dk) => availableDays.findIndex((d) => d.key === dk))
      .filter((i) => i >= 0);
    if (!indices.length) return false;
    return Math.max(...indices) >= availableDays.length - 1;
  }

  function toggleDay(dk: string) {
    setSelectedDays((prev) => {
      const next = prev.includes(dk)
        ? prev.length > 1
          ? prev.filter((x) => x !== dk)
          : prev
        : [...prev, dk];
      if (mode === "couple" && coupleSession?.code) {
        apiFetch(`/api/tinder/sessions/${coupleSession.code}/days`, {
          method: "PUT",
          body: JSON.stringify({ target_days: next }),
        }).catch(() => {});
      }
      return next;
    });
  }

  function advanceSelectedDays(currentDays: string[]): string[] {
    const indices = currentDays
      .map((dk) => availableDays.findIndex((d) => d.key === dk))
      .filter((i) => i >= 0);
    if (!indices.length) return [availableDays[0].key];

    const span = currentDays.length;
    const maxIdx = Math.max(...indices);
    const nextStart = (maxIdx + 1) % availableDays.length;

    const nextDays: string[] = [];
    for (let offset = 0; offset < span; offset++) {
      const idx = nextStart + offset;
      if (idx >= availableDays.length) break;
      nextDays.push(availableDays[idx].key);
    }
    return nextDays.length ? nextDays : [availableDays[0].key];
  }

  async function createCoupleRoom() {
    setCoupleError("");
    try {
      const created = await apiFetch<TinderSessionState>("/api/tinder/sessions", {
        method: "POST",
        body: JSON.stringify({ meal_type: mealType, target_days: selectedDays }),
      });
      seenMatchIds.current = new Set();
      setUserSlot("p1");
      setCoupleSession(created);
    } catch (e: any) {
      setCoupleError(e.message || "Nem sikerült szobát létrehozni");
    }
  }

  async function joinCoupleRoom(e: React.FormEvent) {
    e.preventDefault();
    const code = joinCodeInput.trim().toUpperCase();
    if (!code) return;
    setCoupleError("");
    try {
      const sess = await apiFetch<TinderSessionState>(`/api/tinder/sessions/${code}`);
      seenMatchIds.current = new Set(sess.matches.map((m) => m.id));
      setUserSlot("p2");
      setMealType(sess.meal_type);
      setSelectedDays(sess.target_days.length ? sess.target_days : [availableDays[0].key]);
      setCoupleSession(sess);
    } catch (err: any) {
      setCoupleError(err.message || "Nincs ilyen kódú szoba");
    }
  }

  async function triggerSwipe(dir: "left" | "right") {
    if (!current || saving || flyDir) return;
    setFlyDir(dir);
    setDragX(dir === "right" ? 440 : -440);

    if (mode === "couple" && coupleSession) {
      setSaving(true);
      try {
        const res = await apiFetch<TinderSwipeResult>(
          `/api/tinder/sessions/${coupleSession.code}/swipe`,
          {
            method: "POST",
            body: JSON.stringify({
              user_slot: userSlot,
              recipe_id: current.id,
              decision: dir === "right" ? "like" : "pass",
            }),
          }
        );
        setCoupleSession(res.session);
        if (res.is_match && res.matched_recipe) {
          seenMatchIds.current.add(res.matched_recipe.id);
          setCelebrateMatch(res.matched_recipe);
        }
      } finally {
        setSaving(false);
      }
    } else if (dir === "right") {
      setSaving(true);
      try {
        await onAcceptRecipe(selectedDays, mealType, current);
        const dayNames = selectedDays
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.short || dk)
          .join("+");
        if (isFinalStepOfWeek(selectedDays)) {
          setLastPicked(`✅ ${current.title} (${dayNames})`);
          triggerWeekCompleted(mealType);
          return;
        }
        const nextDays = advanceSelectedDays(selectedDays);
        setSelectedDays(nextDays);
        const nextLabel = nextDays
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.label || dk)
          .join(" + ");
        setLastPicked(`✅ ${current.title} (${dayNames}) · Következő: ${nextLabel}`);
      } finally {
        setSaving(false);
      }
    }

    setTimeout(() => {
      setFlyDir(null);
      setDragX(0);
      setDragY(0);
      setIndex((i) => i + 1);
    }, 210);
  }

  async function acceptCelebratedMatch() {
    if (!celebrateMatch) return;
    setSaving(true);
    try {
      const targetD = selectedDays.length
        ? selectedDays
        : coupleSession?.target_days?.length
        ? coupleSession.target_days
        : [availableDays[0].key];

      if (mode === "couple" && coupleSession) {
        const res = await apiFetch<{
          already_accepted?: boolean;
          placed_days?: string[];
          is_completed?: boolean;
          session: TinderSessionState;
        }>(`/api/tinder/sessions/${coupleSession.code}/accept`, {
          method: "POST",
          body: JSON.stringify({
            days: targetD,
            meal_type: mealType,
            recipe_id: celebrateMatch.id,
          }),
        });
        setCoupleSession(res.session);
        seenAcceptedCount.current = (res.session.accepted_matches || []).length;
        if (res.session.target_days?.length) {
          setSelectedDays(res.session.target_days);
        }
        if (onRefreshAfterCoupleAccept) await onRefreshAfterCoupleAccept();

        const placed = res.placed_days?.length ? res.placed_days : targetD;
        const dayNames = placed
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.short || dk)
          .join("+");

        if (res.is_completed || isFinalStepOfWeek(placed)) {
          setLastPicked(`💚 Közös kedvenc mentve: ${celebrateMatch.title} (${dayNames})`);
          triggerWeekCompleted(mealType);
          return;
        }
        const nextLabel = (res.session.target_days || [])
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.label || dk)
          .join(" + ");
        setLastPicked(`💚 Közös kedvenc mentve: ${celebrateMatch.title} (${dayNames}) · Köv.: ${nextLabel}`);
        setCelebrateMatch(null);
      } else {
        await onAcceptRecipe(targetD, mealType, celebrateMatch);
        const dayNames = targetD
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.short || dk)
          .join("+");
        if (isFinalStepOfWeek(targetD)) {
          setLastPicked(`💚 Mentve: ${celebrateMatch.title} (${dayNames})`);
          triggerWeekCompleted(mealType);
          return;
        }
        const nextDays = advanceSelectedDays(targetD);
        setSelectedDays(nextDays);
        const nextLabel = nextDays
          .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.label || dk)
          .join(" + ");
        setLastPicked(`💚 Mentve: ${celebrateMatch.title} (${dayNames}) · Köv.: ${nextLabel}`);
        setCelebrateMatch(null);
      }
    } finally {
      setSaving(false);
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (celebrateMatch) return;
      if (e.key === "ArrowLeft") triggerSwipe("left");
      else if (e.key === "ArrowRight") triggerSwipe("right");
      else if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>) {
    if (saving || flyDir || celebrateMatch) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    startPos.current = { x: e.clientX, y: e.clientY };
    setIsDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!isDragging || !startPos.current) return;
    setDragX(e.clientX - startPos.current.x);
    setDragY((e.clientY - startPos.current.y) * 0.22);
  }

  function onPointerUp() {
    if (!isDragging) return;
    setIsDragging(false);
    startPos.current = null;
    if (dragX > 90) {
      triggerSwipe("right");
    } else if (dragX < -90) {
      triggerSwipe("left");
    } else {
      setDragX(0);
      setDragY(0);
    }
  }

  const hMeta = current
    ? HEALTHY_META[current.healthy_score || 3] || HEALTHY_META[3]
    : HEALTHY_META[3];
  const dragProgress = Math.min(1, Math.abs(dragX) / 140);
  const likeOpacity = Math.min(1, Math.max(0, (dragX - 20) / 80));
  const passOpacity = Math.min(1, Math.max(0, (-dragX - 20) / 80));

  const mealGradient =
    mealType === "reggeli"
      ? "from-amber-400 via-orange-500 to-rose-500"
      : mealType === "ebed"
      ? "from-[#7AB116] via-[#5C870E] to-[#2F4712]"
      : "from-slate-700 via-emerald-900 to-[#182606]";

  const showCoupleLobby = mode === "couple" && !coupleSession;
  const selectedDayShortLabel = selectedDays
    .map((dk) => DAYS_LIST.find((d) => d.key === dk)?.label || dk)
    .join(" + ");

  const partnerSwipeCount = coupleSession
    ? userSlot === "p1"
      ? coupleSession.p2_swiped_ids.length
      : coupleSession.p1_swiped_ids.length
    : 0;

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/75 backdrop-blur-md flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="relative w-full max-w-[440px] max-h-[95dvh] flex flex-col rounded-t-[2rem] sm:rounded-[2rem] bg-[#F6F6F2] dark:bg-[#141812] border border-slate-200/80 dark:border-white/10 shadow-2xl overflow-hidden">
        {/* 🎉 KÖZÖS KEDVENC! ÜNNEPLŐ OVERLAY */}
        {celebrateMatch && (
          <div className="absolute inset-0 z-40 bg-gradient-to-br from-[#6FA014]/98 via-[#4F770D]/98 to-[#1E2E08]/98 backdrop-blur-xl p-6 flex flex-col items-center justify-center text-center text-white space-y-5">
            <div className="w-16 h-16 rounded-3xl bg-white/15 flex items-center justify-center shadow-inner">
              <PartyPopper className="w-9 h-9 text-amber-200 animate-bounce" />
            </div>
            <div>
              <div className="text-[11px] font-extrabold uppercase tracking-[0.2em] text-amber-200">
                Mindketten ezt választottátok!
              </div>
              <h3 className="text-3xl font-black mt-1 tracking-tight">Közös Kedvenc! 🍲💚</h3>
            </div>
            {celebrateMatch.image_url ? (
              <img
                src={celebrateMatch.image_url}
                alt={celebrateMatch.title}
                className="w-44 h-44 rounded-3xl object-cover shadow-2xl ring-4 ring-white/30"
              />
            ) : (
              <div className="w-36 h-36 rounded-3xl bg-white/15 flex items-center justify-center">
                <ChefHat className="w-16 h-16 text-white/70" />
              </div>
            )}
            <div>
              <div className="text-xl font-extrabold">{celebrateMatch.title}</div>
              <div className="text-xs text-emerald-100 mt-1">
                Cél nap(ok): <strong>{selectedDayShortLabel}</strong>
              </div>
            </div>
            <div className="w-full space-y-2.5 pt-1">
              <button
                type="button"
                disabled={saving}
                onClick={acceptCelebratedMatch}
                className="w-full py-3.5 rounded-2xl bg-white text-emerald-950 hover:bg-emerald-50 font-extrabold text-sm shadow-xl active:scale-[0.98] transition"
              >
                {saving ? "Mentés..." : "✅ Beteszem a heti menübe!"}
              </button>
              <button
                type="button"
                onClick={() => setCelebrateMatch(null)}
                className="w-full py-2.5 rounded-2xl bg-white/15 hover:bg-white/20 text-white font-semibold text-xs transition"
              >
                Tovább válogatok
              </button>
            </div>
          </div>
        )}

        {/* LETISZTULT PRÉMIUM FEJLÉC */}
        <div className="px-5 pt-4 pb-3 bg-white dark:bg-[#1A2016] border-b border-slate-200/70 dark:border-white/5 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-2xl bg-gradient-to-br from-[#7AB116] to-[#4F770D] text-white flex items-center justify-center shadow-md shadow-[#6FA014]/25">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-extrabold text-[15px] text-slate-900 dark:text-white leading-none">
                {mode === "couple" ? "Közös Menüválasztó" : "Menüválasztó"}
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-1 font-medium">
                {selectedDayShortLabel}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {/* Egyéni / Páros szegmens kapcsoló */}
            <div className="flex rounded-full bg-slate-100 dark:bg-[#11150F] p-0.5 border border-slate-200/80 dark:border-white/10">
              <button
                type="button"
                onClick={() => setMode("solo")}
                className={`px-2.5 py-1 rounded-full text-[11px] font-bold flex items-center gap-1 transition ${
                  mode === "solo"
                    ? "bg-white dark:bg-[#6FA014] text-slate-900 dark:text-white shadow-xs"
                    : "text-slate-500"
                }`}
              >
                <User className="w-3 h-3" /> Egyedül
              </button>
              <button
                type="button"
                onClick={() => setMode("couple")}
                className={`px-2.5 py-1 rounded-full text-[11px] font-bold flex items-center gap-1 transition ${
                  mode === "couple"
                    ? "bg-[#6FA014] text-white shadow-xs"
                    : "text-slate-500"
                }`}
              >
                <Users className="w-3 h-3" /> Páros
              </button>
            </div>

            <button
              type="button"
              onClick={() => setShowFilters((v) => !v)}
              className={`p-2 rounded-full border transition ${
                showFilters
                  ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-700 dark:text-emerald-300"
                  : "bg-slate-100 dark:bg-white/5 border-transparent text-slate-500"
              }`}
              title="Napok és szűrők"
            >
              <SlidersHorizontal className="w-4 h-4" />
            </button>

            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-full bg-slate-100 dark:bg-white/5 text-slate-500 hover:text-slate-900 dark:hover:text-white transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* KOMPAKT KATEGÓRIA PILL + LENYITHATÓ NAP-ÉS EGÉSZSÉG SZŰRŐ */}
        <div className="px-4 py-2.5 bg-white/80 dark:bg-[#171C14] border-b border-slate-200/70 dark:border-white/5 space-y-2.5">
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
                  disabled={mode === "couple" && Boolean(coupleSession)}
                  onClick={() => setMealType(m.id)}
                  className={`py-2 rounded-2xl text-xs font-bold flex items-center justify-center gap-1.5 transition disabled:opacity-60 ${
                    active
                      ? "bg-[#6FA014] text-white shadow-sm shadow-[#6FA014]/25"
                      : "bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-300 hover:bg-slate-200/70"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  {m.label}
                </button>
              );
            })}
          </div>

          {(showFilters || (mode === "couple" && !coupleSession)) && (
            <div className="flex items-center justify-between gap-2 pt-0.5">
              <div className="flex gap-1 overflow-x-auto no-scrollbar">
                {availableDays.map((d) => {
                  const active = selectedDays.includes(d.key);
                  return (
                    <button
                      type="button"
                      key={d.key}
                      onClick={() => toggleDay(d.key)}
                      className={`px-2.5 py-1 rounded-xl text-[11px] font-bold border transition flex items-center gap-0.5 ${
                        active
                          ? "bg-slate-900 text-white border-slate-900 dark:bg-emerald-500 dark:text-slate-950 dark:border-emerald-500"
                          : "bg-white dark:bg-[#1C2218] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-white/10"
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
                className={`shrink-0 px-2.5 py-1 rounded-xl text-[11px] font-bold border transition ${
                  healthyOnly
                    ? "bg-emerald-500/20 text-emerald-800 dark:text-emerald-300 border-emerald-500/40"
                    : "bg-white dark:bg-[#1C2218] text-slate-500 border-slate-200 dark:border-white/10"
                }`}
              >
                💚 4-5
              </button>
            </div>
          )}

          {/* Aktív Páros Szoba státusz sáv */}
          {mode === "couple" && coupleSession && (
            <div className="flex items-center justify-between rounded-2xl bg-emerald-500/10 border border-emerald-500/25 px-3 py-1.5 text-xs">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-extrabold text-emerald-800 dark:text-emerald-300 font-mono text-sm tracking-wider">
                  {coupleSession.code}
                </span>
                <span className="text-[11px] text-slate-600 dark:text-slate-300 truncate">
                  {userSlot === "p1" ? "Te (1. fő)" : "Te (2. fő)"} · Partner: {partnerSwipeCount} húzás · 💚{" "}
                  {coupleSession.matches.length}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(coupleSession.code);
                    setCopiedCode(true);
                    setTimeout(() => setCopiedCode(false), 1800);
                  }}
                  className="px-2 py-0.5 rounded-lg bg-white/80 dark:bg-white/10 text-emerald-700 dark:text-emerald-300 font-bold text-[11px] flex items-center gap-1"
                >
                  <Copy className="w-3 h-3" /> {copiedCode ? "Másolva!" : "Kód"}
                </button>
                <button
                  type="button"
                  onClick={() => setCoupleSession(null)}
                  className="text-[11px] text-slate-500 hover:text-rose-500 px-1"
                >
                  Kilép
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Utolsó választás pill */}
        {lastPicked && (
          <div className="px-4 py-1.5 bg-emerald-600 text-white text-xs font-semibold text-center">
            {lastPicked}
          </div>
        )}

        {/* HÉT KÉSZ — AUTOMATIKUS KILÉPÉS OVERLAY */}
        {completedBanner && (
          <div className="absolute inset-0 z-40 bg-emerald-950/92 backdrop-blur-md flex flex-col items-center justify-center p-6 text-center animate-in fade-in">
            <div className="w-20 h-20 rounded-full bg-[#6FA014] text-white flex items-center justify-center shadow-2xl shadow-[#6FA014]/40 mb-4">
              <Check className="w-10 h-10 stroke-[3]" />
            </div>
            <h3 className="text-2xl font-black text-white">{completedBanner}</h3>
            {lastPicked && (
              <p className="text-sm text-emerald-100 mt-2 font-medium">{lastPicked}</p>
            )}
            <p className="text-xs text-emerald-300/80 mt-2">
              Visszatérés a heti menühöz...
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-5 px-6 py-2.5 rounded-2xl bg-white text-emerald-950 font-extrabold text-sm shadow-lg"
            >
              Vissza a heti menühöz
            </button>
          </div>
        )}

        {/* PÁROS LOBBY VAGY PRÉMIUM 3D KÁRTYAPAKLI */}
        {showCoupleLobby ? (
          <div className="p-6 space-y-5 text-center">
            <div className="w-16 h-16 mx-auto rounded-3xl bg-gradient-to-br from-[#7AB116] to-[#47690C] text-white flex items-center justify-center shadow-xl shadow-[#6FA014]/25">
              <Users className="w-8 h-8" />
            </div>
            <div>
              <h4 className="font-extrabold text-xl text-slate-900 dark:text-white tracking-tight">
                Közös Menüválasztó
              </h4>
              <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
                Indíts egy 4 jegyű szobakódot, a párod lépjen be a saját telefonján — mindketten{" "}
                <strong>ugyanazokat a recepteket</strong> látjátok, és amire mindketten igent
                mondtok, azonnal bekerül a heti menübe!
              </p>
            </div>

            <button
              type="button"
              onClick={createCoupleRoom}
              className="w-full py-3.5 rounded-2xl bg-[#6FA014] hover:bg-[#5C870E] text-white font-extrabold text-sm shadow-lg shadow-[#6FA014]/25 active:scale-[0.99] transition"
            >
              ✨ Új közös szoba indítása (1. Fő)
            </button>

            <div className="relative flex items-center py-0.5">
              <div className="flex-grow border-t border-slate-200 dark:border-white/10" />
              <span className="px-3 text-xs text-slate-400">vagy csatlakozz szobakóddal</span>
              <div className="flex-grow border-t border-slate-200 dark:border-white/10" />
            </div>

            <form onSubmit={joinCoupleRoom} className="flex gap-2">
              <input
                type="text"
                maxLength={6}
                value={joinCodeInput}
                onChange={(e) => setJoinCodeInput(e.target.value.toUpperCase())}
                placeholder="4 jegyű kód (pl. K7M2)"
                className="flex-1 text-center font-mono font-extrabold tracking-widest uppercase bg-white dark:bg-[#1C2218] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-[#6FA014]"
              />
              <button
                type="submit"
                className="px-5 py-3 rounded-2xl bg-slate-900 dark:bg-white text-white dark:text-slate-950 font-extrabold text-sm"
              >
                Belépés
              </button>
            </form>

            {coupleError && <p className="text-xs text-rose-500 font-semibold">{coupleError}</p>}
          </div>
        ) : (
          <>
            <div className="relative flex-1 min-h-[410px] sm:min-h-[440px] px-4 pt-4 pb-2 flex items-center justify-center overflow-hidden select-none">
              {!current ? (
                <div className="text-center space-y-3.5 p-6">
                  <div className="w-16 h-16 mx-auto rounded-3xl bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <div className="font-extrabold text-lg text-slate-900 dark:text-white">
                    {deck.length === 0
                      ? "Nincs recept ebben a kategóriában"
                      : "Végigértél a receptpaklin!"}
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 max-w-xs mx-auto">
                    {mode === "couple" && coupleSession
                      ? `Eddig ${coupleSession.matches.length} közös kedvenc született. Amint a párod is végigér, itt azonnal felugrik a találat!`
                      : "Keverd újra a paklit, vagy válts másik étkezési kategóriára felül."}
                  </p>
                  {coupleSession && coupleSession.matches.length > 0 && (
                    <div className="flex flex-wrap justify-center gap-1.5 pt-1">
                      {coupleSession.matches.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          onClick={() => setCelebrateMatch(m)}
                          className="text-xs font-bold px-3 py-1.5 rounded-full bg-emerald-500/15 text-emerald-800 dark:text-emerald-300 border border-emerald-500/30"
                        >
                          💚 {m.title}
                        </button>
                      ))}
                    </div>
                  )}
                  {deck.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setDeckSeed((s) => s + 1)}
                      className="px-5 py-2.5 rounded-2xl bg-[#6FA014] text-white font-bold text-xs inline-flex items-center gap-1.5 shadow-md"
                    >
                      <RotateCcw className="w-3.5 h-3.5" /> Pakli újrakeverése
                    </button>
                  )}
                </div>
              ) : (
                <div className="relative w-full h-[395px] sm:h-[420px]">
                  {/* 3. réteg mélység */}
                  {thirdCard && (
                    <div className="absolute inset-0 rounded-[1.75rem] bg-white/60 dark:bg-[#1F261A]/60 border border-slate-200/70 dark:border-white/5 scale-[0.88] translate-y-6 opacity-40 pointer-events-none" />
                  )}

                  {/* 2. kártya (dinamikusan emelkedik húzáskor!) */}
                  {nextCard && (
                    <div
                      style={{
                        transform: `scale(${0.93 + dragProgress * 0.05}) translateY(${
                          14 - dragProgress * 10
                        }px)`,
                        opacity: 0.65 + dragProgress * 0.3,
                      }}
                      className="absolute inset-0 rounded-[1.75rem] bg-white dark:bg-[#1E251A] border border-slate-200 dark:border-white/10 shadow-lg pointer-events-none transition-transform duration-150"
                    />
                  )}

                  {/* AKTÍV PRÉMIUM HERO KÁRTYA */}
                  <div
                    onPointerDown={onPointerDown}
                    onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp}
                    onPointerCancel={onPointerUp}
                    style={{
                      transform: `translate3d(${dragX}px, ${dragY}px, 0) rotate(${dragX * 0.04}deg)`,
                      transition: isDragging ? "none" : "transform 0.22s cubic-bezier(0.22, 1, 0.36, 1)",
                      touchAction: "none",
                    }}
                    className={`absolute inset-0 rounded-[1.75rem] bg-white dark:bg-[#1C2218] shadow-2xl overflow-hidden flex flex-col cursor-grab active:cursor-grabbing border transition-shadow ${
                      dragX > 35
                        ? "border-emerald-400 ring-4 ring-emerald-400/25"
                        : dragX < -35
                        ? "border-rose-400 ring-4 ring-rose-400/25"
                        : "border-slate-200/90 dark:border-white/10"
                    }`}
                  >
                    {/* Nagy Hero Kép (a kártya felső 64%-a!) */}
                    <div className="relative h-[64%] w-full shrink-0 overflow-hidden">
                      {current.image_url ? (
                        <img
                          src={current.image_url}
                          alt={current.title}
                          draggable={false}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div
                          className={`w-full h-full bg-gradient-to-br ${mealGradient} flex items-center justify-center relative`}
                        >
                          <div className="absolute -top-10 -right-10 w-44 h-44 rounded-full bg-white/10 blur-2xl" />
                          <div className="absolute -bottom-10 -left-10 w-44 h-44 rounded-full bg-black/15 blur-2xl" />
                          <UtensilsCrossed className="w-20 h-20 text-white/25" />
                        </div>
                      )}

                      <div className="absolute inset-x-0 bottom-0 h-32 bg-gradient-to-t from-black/85 via-black/40 to-transparent" />

                      {/* Dinamikus Pill-pecsétek húzás közben */}
                      {likeOpacity > 0.05 && (
                        <div
                          style={{ opacity: likeOpacity }}
                          className="absolute top-4 left-4 px-4 py-1.5 rounded-2xl bg-[#6FA014]/90 text-white font-black text-base tracking-wide shadow-xl backdrop-blur-md -rotate-6 border border-white/30"
                        >
                          VÁLASZTOM 💚
                        </div>
                      )}
                      {passOpacity > 0.05 && (
                        <div
                          style={{ opacity: passOpacity }}
                          className="absolute top-4 right-4 px-4 py-1.5 rounded-2xl bg-rose-600/90 text-white font-black text-base tracking-wide shadow-xl backdrop-blur-md rotate-6 border border-white/30"
                        >
                          TOVÁBB ✕
                        </div>
                      )}

                      {/* Felső glassmorphism badge-ek */}
                      <div className="absolute top-3.5 inset-x-3.5 flex items-center justify-between gap-2 pointer-events-none">
                        <span className="px-2.5 py-1 rounded-full bg-black/45 backdrop-blur-md text-white text-[11px] font-bold border border-white/15">
                          {index + 1} / {deck.length}
                        </span>
                        <span className="px-2.5 py-1 rounded-full bg-black/45 backdrop-blur-md text-white text-[11px] font-bold border border-white/15">
                          {hMeta.emoji} {current.healthy_score || 3}/5 · {hMeta.label}
                        </span>
                      </div>

                      {/* Cím + Makrók a kép alján */}
                      <div className="absolute bottom-3.5 left-4 right-4 space-y-1">
                        <h4 className="text-2xl font-black text-white leading-tight drop-shadow-sm">
                          {current.title}
                        </h4>
                        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                          <span className="px-2 py-0.5 rounded-full bg-white/20 backdrop-blur-md text-white font-semibold">
                            {current.servings} adag
                          </span>
                          {current.kcal_per_serving > 0 && (
                            <span className="px-2.5 py-0.5 rounded-full bg-amber-400/25 backdrop-blur-md text-amber-100 font-bold border border-amber-300/30">
                              🔥 {current.kcal_per_serving} kcal · P {Math.round(current.protein_g)}g · CH{" "}
                              {Math.round(current.carbs_g)}g · Zs {Math.round(current.fat_g)}g
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Alsó letisztult hozzávaló-csík */}
                    <div className="p-4 flex-1 overflow-y-auto flex flex-col justify-between bg-white dark:bg-[#1C2218]">
                      <div className="flex flex-wrap gap-1.5">
                        {current.ingredients.slice(0, 7).map((ing, i) => (
                          <span
                            key={i}
                            className="text-[11px] font-medium px-2.5 py-1 rounded-xl bg-[#F6F6F2] dark:bg-[#121510] border border-slate-200/80 dark:border-white/5 text-slate-700 dark:text-slate-300"
                          >
                            {ing.name}{" "}
                            <span className="text-slate-400">
                              {ing.quantity} {ing.unit}
                            </span>
                          </span>
                        ))}
                        {current.ingredients.length > 7 && (
                          <span className="text-[11px] px-2 py-1 text-slate-400 font-semibold">
                            +{current.ingredients.length - 7} további
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* LEBEGŐ PRÉMIUM AKCIÓ DOCK */}
            <div className="px-5 pt-2 pb-5 flex items-center justify-center gap-4">
              <button
                type="button"
                disabled={index === 0}
                onClick={() => setIndex((i) => Math.max(0, i - 1))}
                className="w-12 h-12 rounded-2xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/10 text-amber-500 hover:bg-amber-50 dark:hover:bg-white/10 flex items-center justify-center shadow-md disabled:opacity-30 active:scale-90 transition"
                title="Vissza az előzőre"
              >
                <RotateCcw className="w-5 h-5" />
              </button>

              <button
                type="button"
                disabled={!current || saving}
                onClick={() => triggerSwipe("left")}
                className="flex-1 max-w-[130px] h-14 rounded-2xl bg-white dark:bg-[#1C2218] border-2 border-rose-500/30 text-rose-600 dark:text-rose-400 hover:bg-rose-500 hover:text-white hover:border-rose-500 flex items-center justify-center gap-1.5 font-extrabold text-sm shadow-lg active:scale-95 transition disabled:opacity-30"
              >
                <X className="w-5 h-5" />
                <span>Tovább</span>
              </button>

              <button
                type="button"
                disabled={!current || saving}
                onClick={() => triggerSwipe("right")}
                className="flex-1 max-w-[140px] h-14 rounded-2xl bg-gradient-to-r from-[#7AB116] to-[#5C870E] hover:brightness-105 text-white flex items-center justify-center gap-1.5 font-extrabold text-sm shadow-xl shadow-[#6FA014]/30 active:scale-95 transition disabled:opacity-30"
              >
                <Heart className="w-5 h-5 fill-current" />
                <span>Választom</span>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
