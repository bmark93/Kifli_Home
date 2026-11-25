# 🥐 kifli.otthon — Privát Heti Menütervező, Kaja Tinder & Kifli.hu MCP Asszisztens

Saját Linux szerveren / NAS-on (egyetlen ~35 MB RAM-os Docker konténerben, belső hálón vagy Tailscale VPN mögött) futó, **Kifli.hu arculatú** mobilbarát PWA és AI bevásárló-asszisztens — **kétirányú MCP integrációval** (kifelé a hivatalos `https://mcp.kifli.hu/mcp` felé, befelé pedig saját **18 toolos MCP szerverrel** Claude mobil app / Desktop számára!).

---

## ✨ Fő funkciók

### 🔥 Kaja Tinder & Páros Match (0 AI token!)
* **Egyéni Swipe mód:** Külön pörgetheted a **🌅 Reggeli**, **🍲 Ebéd** és **🌙 Vacsora** receptjeidet (+ `💚 4-5` egészséges szűrő). Jobbra húzva azonnal bekerül a heti menübe és **automatikusan átugrik a következő nap(ok)ra** (2-napos főzésnél pl. `H+K → Sze+Cs`!).
* **❤️ Páros Kaja Tinder Match:** Indíts egy 4 karakteres szobakódot (pl. `K7M2`), a párod csatlakozik a saját telefonjáról, és amire **mindketten jobbra húztok**, azonnal felugrik az **„IT’S A MATCH! 🍲💚”** és 1 bökéssel mehet a menübe!

### 🏷️ 1-kattintásos Kifli Sajátmárka Optimalizáló + Kedvenc-védelem
* Az élő **🛒 Kosár** fülön 1 gombnyomásra megkeresi a drágább márkák olcsóbb **Kifli saját márkás** alternatíváit (*Miil, Moddia, Yutto, Ubomi, Dacello, Kitchin, Pappudia*).
* **Nem-kedvenc tételek:** azonnal, helyben lecseréli a Kifli kosaradban (nincs chat-átirányítás!).
* **⭐ Kedvelt márkák védelme:** ami a kedvenceid között van, azt nem cseréli le a hátad mögött — egy átlátható **összehasonlító táblázat-popupban** mutatja meg a megtakarítást soronkénti **Csere / Mégse** és felső **Összes cseréje / Mind maradjon** gombokkal!

### 🍲 Okos Heti Menütervező & Kifli Készlet-ellenőrzés
* **Élő Kifli készlet-ellenőrzés:** A heti menü generáláskor ellenőrzi a kulcs-alapanyagokat a Kiflin — ha pl. a frankfurti leveshez épp nincs kelkáposzta, nem ajánlja fel arra a hétre.
* **💚 Healthy Score (1–5):** Minden receptnél állítható (*1 🍔 Bűnözős → 5 💚 Szuper-fitt*), a heti menütervező pedig kiegyensúlyozott heti átlagra törekszik.
* **✨ Szabályozható AI receptajánlások:** Ki/bekapcsolható, beállítható hány új ötletet (`1–5`) és melyik kategóriákba (`Reggeli / Ebéd / Vacsora`) tegyen be.
* **⚡ 0 AI-tokenes kézi csere & Reset:** Bármelyik étkezésre kattintva saját receptekből cserélhetsz több napra egyszerre, vagy 1 gombbal nullázhatod a heti menüt.
* **Smart 2-napos főzés:** A 4+ adagos ebédeket/vacsorákat egymást követő két napon **1 főzésként** számolja össze (nem duplázza feleslegesen a hozzávalókat!).

### 🥗 Diéta, Allergén-helyettesítés & Büdzsé-korlát
* **Valódi laktózmentes & gluténmentes helyettesítés:** Ha bekapcsolod a `laktóz` vagy `glutén` szűrőt, nem kihagyja a tejet/tejfölt/tésztát, hanem kódszinten **`laktózmentes` / `gluténmentes`** keresőcímkét tesz rájuk, és a sajátmárka-optimalizáló is szigorúan csak mentes termékre cserélhet!
* **💰 Heti büdzsé-korlát (Ft):** Vizuális % sávval mutatja az élő kosárban, hol állsz a heti kerethez képest.
* **♻️ Akciók & „Mentsd meg az ételt” fókusz** + **Kamra-alapanyagok** (só, bors, olaj, liszt…) automatikus kihagyása.

### 🧻 Anti-Loop Háztartási Lista & 🧠 Smart Restock
* Külön egyszeri lista tisztítószernek, papírzsepinek stb. opcionális pontos márkával.
* **3-lépcsős anti-loop állapotgép (`PENDING → IN_CART → ORDERED`):** Ami készlethiányos maradt, nem vész el; amit megrendeltél, végleg lezárul, így **soha nem loopol a következő héten**.
* **🧠 Smart Restock (0 AI token):** A Kifli rendelési előzményekből és a helyi előzményekből kiszámolja a fogyási ciklusokat, és 1 bökéssel visszateheted a listára, ami várhatóan elfogyott.

### 📸 Receptek Fotóval, Szerkesztéssel & AI Importtal
* Kézi felvétel, teljes szerkesztés, **fotó feltöltés telefonról/gépről** (vagy Claude MCP-n keresztül URL/base64-ből), plusz 1-kattintásos **AI recept-import** linkből vagy szövegből.
* **Kifli.hu natív Light & Dark mód**, mobil alsó Tab Bar + teljes szélességű Widescreen desktop elrendezés.
* **Élő Kifli.hu Kosár fül (0 AI token):** Termékfotókkal, valós árakkal, `+ / - / törlés` gombokkal, kedvenc csillagozással és közvetlen `kifli.hu/rendeles/kosaram-tartalma` fizetés gombbal. *(Hard Checkout fék: az AI soha nem ad le fizetős rendelést helyetted!)*

### 📱 Privát Telegram Bot + Hétfő reggeli ütemezés
* Minden hétfőn 08:00-kor küldi a heti menüt Telegramon (`TELEGRAM_ALLOWED_USER_IDS` whitelisttel), természetes nyelven módosítható chatben, és **[✅ Megrendeltem]** gombbal üríti az egyszeri listát.

---

## 🚀 Gyors indítás (Linux szerver / NAS / M4 MacBook Air)

```bash
git clone https://github.com/bmark93/Kifli_Home.git
cd Kifli_Home
cp .env.example .env
# Szerkeszd a .env fájlt: GEMINI_API_KEY (vagy OPENAI_API_KEY), opcionálisan TELEGRAM_BOT_TOKEN és MCP_ACCESS_TOKEN
docker compose up -d --build
```

Elérés belső hálón / VPN-en: 👉 `http://<szerver-ip>:8085`

### Kifli.hu fiók összekötése (OAuth 2.1 PKCE — 1 perc, egyszer kell)
1. Nyisd meg a **⚙️ Kamra** fület → **1. Belépés a Kifli.hu-ra**.
2. Belépés után a böngésző átirányít a `http://localhost:3334/oauth/callback?code=...` címre (ha távoli NAS-on fut, normális, hogy nem tölt be az oldal).
3. Másold be a teljes címsort a **Kamra** fülön megjelenő mezőbe → **Mentés**. Innentől a `./data/kifli_oauth/` alatt a program **automatikusan megújítja** a 8 órás tokeneket a háttérben!

---

## 🔌 Saját beépített MCP Szerver (18 tool — Claude mobil app / Desktop / Code)

Az app saját **Streamable HTTP MCP végpontot** futtat ugyanazon a porton:
* **Belső hálón:** `http://<szerver-ip>:8085/mcp`
* **Publikusan (Claude mobil app + Tailscale Funnel):**
  1. `.env`-ben hagyd üresen az `APP_ACCESS_PIN=` mezőt (így a belső weboldal nem kér PIN-t!), és állíts be egy alfanumerikus **`MCP_ACCESS_TOKEN=...`** kulcsot.
  2. NAS-on nyisd ki **kizárólag az `/mcp` útvonalat** HTTPS-en:
     ```bash
     sudo tailscale funnel --bg --set-path=/mcp http://127.0.0.1:8085/mcp
     ```
  3. A **Claude.ai → Settings → Connectors → Add custom connector** mezőbe írd be (Authentication: *None*):
     ```text
     https://<gepnev>.<tailnet>.ts.net/mcp/<MCP_ACCESS_TOKEN>
     ```

### Elérhető 18 MCP eszköz:
* **Receptek:** `list_recipes`, `upsert_recipe`, `delete_recipe`, `set_recipe_image`, `set_recipe_healthy_score`
* **Heti menü:** `get_weekly_menu`, `set_weekly_meals`, `save_full_weekly_menu`, `reset_weekly_menu`, `add_extra_weekly_item`
* **Háztartás (Anti-Loop):** `list_household_items`, `add_household_item`, `delete_household_item`, `confirm_order_and_clear_household_items`
* **Bevásárlás & Preferenciák:** `get_aggregated_shopping_list`, `save_preferred_kifli_product`, `get_planner_settings`, `update_planner_settings`

