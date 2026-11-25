import React, { useState } from "react";
import {
  Sparkles,
  Flame,
  ShoppingBasket,
  ShieldCheck,
  LogIn,
  UserPlus,
  Sun,
  Moon,
  KeyRound,
} from "lucide-react";
import { apiFetch, type AuthConfig, type UserProfile } from "./api";

interface Props {
  config: AuthConfig;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onAuthenticated: (user: UserProfile) => void;
}

export function LoginView({ config, theme, onToggleTheme, onAuthenticated }: Props) {
  const [mode, setMode] = useState<"login" | "register">(
    config.has_registered_users ? "login" : "register"
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "register") {
        const user = await apiFetch<UserProfile>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({
            email: email.trim(),
            password,
            display_name: displayName.trim(),
            invite_code: inviteCode.trim(),
          }),
        });
        onAuthenticated(user);
      } else {
        const user = await apiFetch<UserProfile>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ email: email.trim(), password }),
        });
        onAuthenticated(user);
      }
    } catch (err: any) {
      setError(err.message || "Sikertelen belépés");
    } finally {
      setBusy(false);
    }
  }

  async function handleDemoLogin() {
    setError("");
    setBusy(true);
    try {
      const user = await apiFetch<UserProfile>("/api/auth/demo", { method: "POST" });
      onAuthenticated(user);
    } catch (err: any) {
      setError(err.message || "Nem sikerült elindítani a Demo módot");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-[100dvh] bg-[#F6F6F2] dark:bg-[#121510] text-[#1F241E] dark:text-[#F2F4EE] flex flex-col items-center justify-center p-4 sm:p-6 relative">
      {/* Téma váltó jobb felül */}
      <button
        type="button"
        onClick={onToggleTheme}
        className="fixed top-4 right-4 p-2.5 rounded-2xl bg-white dark:bg-[#1C2218] border border-slate-200 dark:border-white/10 text-slate-700 dark:text-amber-300 shadow-sm"
        title="Téma váltása"
      >
        {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
      </button>

      <div className="w-full max-w-4xl grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
        {/* Bal: Kifli.otthon bemutató kártya */}
        <div className="lg:col-span-6 rounded-3xl bg-gradient-to-br from-[#6FA014] via-[#5C870E] to-[#3F620A] dark:from-[#365314] dark:via-[#263B0F] dark:to-[#182210] p-6 sm:p-8 text-white shadow-xl space-y-6">
          <div className="flex items-center gap-3.5">
            <div className="w-12 h-12 rounded-2xl bg-white/15 backdrop-blur flex items-center justify-center text-3xl ring-2 ring-amber-300/40 shadow-lg">
              🥐
            </div>
            <div>
              <div className="text-2xl font-extrabold tracking-tight leading-none">
                kifli<span className="text-amber-200">.otthon</span>
              </div>
              <div className="text-xs font-semibold text-emerald-100 mt-1">
                Heti Menü · Kaja Tinder · Kifli.hu MCP
              </div>
            </div>
          </div>

          <h1 className="text-xl sm:text-2xl font-extrabold leading-snug">
            1 perc alatt kész a heti menüd és az élő Kifli.hu kosarad.
          </h1>

          <div className="space-y-3 text-xs sm:text-sm text-emerald-50/95">
            <div className="flex items-start gap-2.5">
              <Flame className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" />
              <span>
                <strong>Kaja Tinder &amp; Páros Match:</strong> húzogassátok együtt 2 telefonon a
                recepteket — azonnali heti menü 0 AI tokennel.
              </span>
            </div>
            <div className="flex items-start gap-2.5">
              <ShoppingBasket className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" />
              <span>
                <strong>1-kattintásos Kifli Sajátmárka Optimalizáló:</strong> spórolj ezreket Miil,
                Moddia, Yutto, Kitchin cserékkel — a kedvenceid védelmével!
              </span>
            </div>
            <div className="flex items-start gap-2.5">
              <ShieldCheck className="w-4 h-4 text-amber-300 shrink-0 mt-0.5" />
              <span>
                <strong>Privát Multi-User (BYOK):</strong> minden felhasználó saját receptekkel,
                saját titkosított AI API kulccsal és saját Kifli fiókkal dolgozik.
              </span>
            </div>
          </div>

          {config.demo_mode_enabled && (
            <button
              type="button"
              disabled={busy}
              onClick={handleDemoLogin}
              className="w-full py-3.5 px-5 rounded-2xl bg-white text-emerald-950 hover:bg-emerald-50 active:scale-[0.99] font-extrabold text-sm shadow-xl flex items-center justify-center gap-2 transition disabled:opacity-50"
            >
              <Sparkles className="w-4 h-4 text-[#6FA014]" />
              <span>🎯 Interaktív Kifli Demo kipróbálása (1 kattintás)</span>
            </button>
          )}
        </div>

        {/* Jobb: Login / Regisztráció űrlap */}
        <div className="lg:col-span-6 rounded-3xl bg-white dark:bg-[#1C2218] border border-slate-200/90 dark:border-white/10 p-6 sm:p-7 shadow-xl space-y-5">
          {/* Tab váltó */}
          <div className="grid grid-cols-2 gap-1.5 p-1 rounded-2xl bg-slate-100 dark:bg-[#121510]">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setError("");
              }}
              className={`py-2.5 rounded-xl text-xs sm:text-sm font-bold flex items-center justify-center gap-1.5 transition ${
                mode === "login"
                  ? "bg-white dark:bg-[#1C2218] text-slate-900 dark:text-white shadow-sm"
                  : "text-slate-500"
              }`}
            >
              <LogIn className="w-4 h-4" /> Bejelentkezés
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError("");
              }}
              className={`py-2.5 rounded-xl text-xs sm:text-sm font-bold flex items-center justify-center gap-1.5 transition ${
                mode === "register"
                  ? "bg-white dark:bg-[#1C2218] text-slate-900 dark:text-white shadow-sm"
                  : "text-slate-500"
              }`}
            >
              <UserPlus className="w-4 h-4" /> Új fiók
            </button>
          </div>

          {!config.has_registered_users && mode === "register" && (
            <div className="rounded-2xl bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-500/30 p-3 text-xs text-emerald-800 dark:text-emerald-200">
              👋 <strong>Első indítás:</strong> az első regisztrált fiók lesz az Admin/Tulajdonos,
              és automatikusan megörökli a már meglévő recepteket és Kifli belépést!
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3.5">
            {mode === "register" && (
              <div>
                <label className="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1">
                  Megjelenített név
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Pl. Márk"
                  className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
                />
              </div>
            )}

            <div>
              <label className="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1">
                E-mail cím
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nev@pelda.hu"
                required
                className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1">
                Jelszó {mode === "register" && <span className="font-normal text-slate-400">(min. 6 karakter)</span>}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                minLength={mode === "register" ? 6 : 1}
                className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
              />
            </div>

            {mode === "register" && config.invite_required && (
              <div>
                <label className="block text-xs font-bold text-slate-600 dark:text-slate-300 mb-1 flex items-center gap-1">
                  <KeyRound className="w-3.5 h-3.5 text-emerald-600" /> Meghívókód
                </label>
                <input
                  type="text"
                  value={inviteCode}
                  onChange={(e) => setInviteCode(e.target.value)}
                  placeholder="Kérd el a meghívókódot"
                  required
                  className="w-full bg-slate-100 dark:bg-[#121510] text-slate-900 dark:text-white rounded-2xl px-4 py-3 text-sm border border-slate-200 dark:border-white/10 focus:outline-none focus:border-emerald-500"
                />
              </div>
            )}

            {error && (
              <div className="rounded-2xl bg-rose-50 dark:bg-rose-950/60 border border-rose-500/30 px-3.5 py-2.5 text-xs font-semibold text-rose-700 dark:text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="w-full py-3.5 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-white dark:bg-emerald-500 dark:hover:bg-emerald-400 dark:text-slate-950 font-extrabold text-sm shadow-lg shadow-emerald-500/20 transition disabled:opacity-50"
            >
              {busy
                ? "Folyamatban..."
                : mode === "register"
                ? "Fiók létrehozása és belépés"
                : "Belépés"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
