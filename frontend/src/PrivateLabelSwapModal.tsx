import React, { useState } from "react";
import {
  X,
  Star,
  ArrowRight,
  CheckCircle2,
  Sparkles,
  RefreshCw,
} from "lucide-react";
import { formatFt, type PrivateLabelSwapProposal } from "./api";

interface Props {
  autoSwappedCount: number;
  autoSavingsFt: number;
  proposals: PrivateLabelSwapProposal[];
  busy: boolean;
  onClose: () => void;
  onSwapOne: (proposal: PrivateLabelSwapProposal) => Promise<void>;
  onSwapAll: (remaining: PrivateLabelSwapProposal[]) => Promise<void>;
}

export function PrivateLabelSwapModal({
  autoSwappedCount,
  autoSavingsFt,
  proposals,
  busy,
  onClose,
  onSwapOne,
  onSwapAll,
}: Props) {
  const [swappedIds, setSwappedIds] = useState<number[]>([]);
  const [keptIds, setKeptIds] = useState<number[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);

  const pendingProposals = proposals.filter(
    (p) => !swappedIds.includes(p.old_product_id) && !keptIds.includes(p.old_product_id)
  );
  const potentialSavings = pendingProposals.reduce((acc, p) => acc + p.savings_ft, 0);

  async function handleSwapSingle(p: PrivateLabelSwapProposal) {
    setActiveId(p.old_product_id);
    try {
      await onSwapOne(p);
      setSwappedIds((prev) => [...prev, p.old_product_id]);
    } finally {
      setActiveId(null);
    }
  }

  function handleKeepSingle(oldProductId: number) {
    setKeptIds((prev) => [...prev, oldProductId]);
  }

  async function handleSwapAllClick() {
    if (!pendingProposals.length) {
      onClose();
      return;
    }
    await onSwapAll(pendingProposals);
    setSwappedIds((prev) => [...prev, ...pendingProposals.map((p) => p.old_product_id)]);
    onClose();
  }

  function handleKeepAllClick() {
    setKeptIds(proposals.map((p) => p.old_product_id));
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/75 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="w-full max-w-4xl max-h-[92dvh] flex flex-col rounded-t-3xl sm:rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/10 shadow-2xl overflow-hidden">
        {/* Fejléc */}
        <div className="px-5 py-4 border-b border-slate-200 dark:border-white/10 bg-[#F6F6F2] dark:bg-[#20271C] flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-2xl bg-amber-400/20 border border-amber-400/40 text-amber-600 dark:text-amber-300 flex items-center justify-center shrink-0 mt-0.5">
              <Star className="w-5 h-5 fill-current" />
            </div>
            <div>
              <h3 className="font-extrabold text-base sm:text-lg text-slate-900 dark:text-white leading-snug">
                Kedvelt termékeidhez találtunk olcsóbb Kifli saját márkát
              </h3>
              <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 mt-0.5">
                {proposals.length === 1
                  ? "Látjuk, hogy ez a termék a kedvenceid között szerepel. Lecseréljük a Kifli saját márkás alternatívára, vagy maradjon az eredeti?"
                  : `Látjuk, hogy ${proposals.length} termék a kedvenceid között szerepel. Döntsd el soronként — vagy egy kattintással —, hogy melyik cserélődjön!`}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-full bg-slate-200/70 dark:bg-white/10 text-slate-600 dark:text-slate-300 shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Ha már történt azonnali nem-kedvenc csere */}
        {autoSwappedCount > 0 && (
          <div className="px-5 py-2.5 bg-emerald-50 dark:bg-emerald-950/60 border-b border-emerald-500/20 text-xs sm:text-sm text-emerald-800 dark:text-emerald-200 flex items-center gap-2 font-semibold">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
            <span>
              {autoSwappedCount} nem-kedvenc terméket már automatikusan Kifli saját márkára
              cseréltünk (-{formatFt(autoSavingsFt)})!
            </span>
          </div>
        )}

        {/* Felső tömeges akciósáv */}
        <div className="px-5 py-3 border-b border-slate-200 dark:border-white/10 bg-white dark:bg-[#171C14] flex flex-wrap items-center justify-between gap-2.5">
          <div className="text-xs font-semibold text-slate-600 dark:text-slate-300">
            {pendingProposals.length > 0 ? (
              <>
                Még <strong>{pendingProposals.length}</strong> kedvenc vár döntésre · További
                megtakarítás:{" "}
                <span className="text-emerald-600 dark:text-emerald-400 font-extrabold">
                  -{formatFt(potentialSavings)}
                </span>
              </>
            ) : (
              <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                Minden kedvencnél döntöttél! 🎉
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || pendingProposals.length === 0}
              onClick={handleKeepAllClick}
              className="px-3.5 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-white/10 dark:hover:bg-white/15 text-slate-700 dark:text-slate-200 font-bold text-xs transition disabled:opacity-40"
            >
              Mind maradjon
            </button>
            <button
              type="button"
              disabled={busy || pendingProposals.length === 0}
              onClick={handleSwapAllClick}
              className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 font-extrabold text-xs flex items-center gap-1.5 shadow-sm transition disabled:opacity-40"
            >
              {busy ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Sparkles className="w-3.5 h-3.5" />
              )}
              <span>
                Összes cseréje {potentialSavings > 0 ? `(-${formatFt(potentialSavings)})` : ""}
              </span>
            </button>
          </div>
        </div>

        {/* Táblázat fejléc (Desktop) */}
        <div className="hidden md:grid md:grid-cols-12 gap-3 px-5 py-2.5 bg-slate-50 dark:bg-[#151912] border-b border-slate-200 dark:border-white/5 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          <div className="col-span-4">Jelenlegi kedvelt márka</div>
          <div className="col-span-4">Kifli saját márkás javaslat</div>
          <div className="col-span-2 text-right">Megtakarítás</div>
          <div className="col-span-2 text-right">Döntés</div>
        </div>

        {/* Sorok */}
        <div className="flex-1 overflow-y-auto divide-y divide-slate-200 dark:divide-white/5">
          {proposals.map((p) => {
            const isSwapped = swappedIds.includes(p.old_product_id);
            const isKept = keptIds.includes(p.old_product_id);
            const isRowBusy = activeId === p.old_product_id;

            return (
              <div
                key={p.old_product_id}
                className={`px-5 py-3.5 grid grid-cols-1 md:grid-cols-12 gap-3 items-center transition ${
                  isSwapped
                    ? "bg-emerald-50/70 dark:bg-emerald-950/30 opacity-80"
                    : isKept
                    ? "bg-slate-50/70 dark:bg-white/[0.02] opacity-55"
                    : "bg-white dark:bg-[#1C2218]"
                }`}
              >
                {/* Jelenlegi kedvelt termék */}
                <div className="md:col-span-4 flex items-center gap-3 min-w-0">
                  {p.old_image_url ? (
                    <img
                      src={p.old_image_url}
                      alt={p.old_name}
                      className="w-11 h-11 rounded-xl object-cover bg-white border border-slate-200 dark:border-white/10 shrink-0"
                    />
                  ) : (
                    <div className="w-11 h-11 rounded-xl bg-slate-100 dark:bg-white/5 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <div className="text-[10px] font-bold uppercase text-amber-600 dark:text-amber-400 flex items-center gap-1">
                      <Star className="w-2.5 h-2.5 fill-current" /> Kedvelt termék
                    </div>
                    <div className="text-sm font-semibold text-slate-900 dark:text-white leading-snug line-clamp-2">
                      {p.old_name}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {p.old_quantity} db · <strong>{formatFt(p.old_price_ft)}</strong>
                    </div>
                  </div>
                </div>

                {/* Kifli saját márkás javaslat */}
                <div className="md:col-span-4 flex items-start gap-2 min-w-0">
                  <ArrowRight className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-1 hidden md:block" />
                  <div className="min-w-0">
                    <div className="inline-flex items-center gap-1 text-[10px] font-extrabold uppercase px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
                      🥐 {p.new_brand || "Kifli saját márka"}
                    </div>
                    <div className="text-sm font-bold text-slate-900 dark:text-white leading-snug line-clamp-2 mt-0.5">
                      {p.new_name}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      {p.new_quantity} db {p.new_amount ? `(${p.new_amount})` : ""} ·{" "}
                      <strong className="text-emerald-700 dark:text-emerald-300">
                        {formatFt(p.new_price_ft)}
                      </strong>
                    </div>
                  </div>
                </div>

                {/* Megtakarítás */}
                <div className="md:col-span-2 flex md:flex-col md:items-end justify-between items-center">
                  <span className="text-xs text-slate-500 md:hidden">Megtakarítás:</span>
                  <span className="inline-flex items-center px-2.5 py-1 rounded-xl bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 font-black text-sm">
                    -{formatFt(p.savings_ft)}
                  </span>
                </div>

                {/* Soronkénti 2 gomb */}
                <div className="md:col-span-2 flex items-center justify-end gap-2">
                  {isSwapped ? (
                    <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                      <CheckCircle2 className="w-4 h-4" /> Kicserélve
                    </span>
                  ) : isKept ? (
                    <span className="text-xs font-semibold text-slate-400">Megmaradt</span>
                  ) : (
                    <>
                      <button
                        type="button"
                        disabled={busy || isRowBusy}
                        onClick={() => handleSwapSingle(p)}
                        className="flex-1 md:flex-none px-3.5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 font-bold text-xs shadow-sm transition disabled:opacity-50"
                      >
                        {isRowBusy ? "..." : "Csere"}
                      </button>
                      <button
                        type="button"
                        disabled={busy || isRowBusy}
                        onClick={() => handleKeepSingle(p.old_product_id)}
                        className="flex-1 md:flex-none px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-white/10 dark:hover:bg-white/15 text-slate-700 dark:text-slate-300 font-semibold text-xs transition disabled:opacity-50"
                      >
                        Mégse
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Lábléc bezárás gomb */}
        <div className="px-5 py-3 border-t border-slate-200 dark:border-white/10 bg-[#F6F6F2] dark:bg-[#20271C] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2.5 rounded-xl bg-slate-900 dark:bg-white/15 text-white font-bold text-xs"
          >
            Kész, vissza a kosárhoz
          </button>
        </div>
      </div>
    </div>
  );
}
