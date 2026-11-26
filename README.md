# 🥐 kifli.otthon — Okos Heti Menütervező, Közös Menüválasztó & Kifli.hu MCP Asszisztens

Saját szerveren / NAS-on (~35 MB RAM-os Docker konténerben) vagy felhőben (pl. **Railway**) futó, **Kifli.hu arculatú**, többfelhasználós mobilbarát PWA és AI bevásárló-asszisztens — **kétirányú MCP integrációval** (kifelé a hivatalos `https://mcp.kifli.hu/mcp` felé, befelé pedig felhasználónkénti **20 toolos Streamable HTTP MCP szerverrel** Claude mobil app / Desktop számára!).

---

## ✨ Fő funkciók

### 🏠 Családi / Háztartási Fiók Összekapcsolása
* **Közös háztartás 6 karakteres meghívókóddal:** A háztartás tagjai (pár, gyerekek, lakótársak) a saját fiókjukból 1 kattintással csatlakozhatnak ugyanahhoz a háztartáshoz (`Beállítások` → *Családi / Háztartási fiók összekapcsolása*).
* Minden összekapcsolt tag közösen használja ugyanazt a **Kifli.hu fiókot és élő kosarat**, a **receptkönyvet**, a **heti menüt**, a **kamrát**, a **háztartási listát**, az **AI API kulcsot** és a **Claude MCP-t**.

### 💚 Menüválasztó & Közös Menüválasztó (0 AI token!)
* **Egyéni 3D kártyapakli mód:** Külön pörgetheted a **🌅 Reggeli**, **🍲 Ebéd** és **🌙 Vacsora** receptjeidet (+ `💚 4-5` egészséges szűrő). Jobbra húzva azonnal bekerül a heti menübe és **automatikusan átugrik a következő nap(ok)ra** (pl. 2-napos főzésnél `H+K → Sze+Cs`!).
* **❤️ Közös Menüválasztó (valós idejű szinkronnal):** Indíts egy 4 karakteres szobakódot (pl. `K7M2`), a párod csatlakozik a saját telefonjáról, és mindketten **ugyanazt a receptpaklit** látjátok. A szerver szinkronizálja a cél-napokat és az elfogadott közös kedvenceket — ha végigértek a héten (vagy minden napra választottatok), automatikusan visszaigazol és visszatér a heti menühöz!

### 🌍 Recept Válogatás (Kifli.hu + Közösség + Saját, Nyilvános / Privát)
* **Nyilvános / Privát receptek:** Minden saját recepted 1 kattintással publikálható a közösségi válogatásba (vagy visszavehető privátra) a kártyán, a szerkesztőben vagy Claude MCP-ből (`set_recipe_visibility`).
* **Élő Kifli.hu recept szinkron (0 AI token!):** A **Receptek → Recept válogatás** nézetben közvetlenül böngészheted a Kifli.hu receptjeit és a közösségi recepteket (**Összes / Kifli.hu / Közösség / Saját** szűrőkkel), és **1 gombbal elmentheted** őket a saját receptkönyvedbe fotóval, hozzávalókkal és lépésekkel együtt.
* **📚 Választható AI receptforrások:** A *Beállítások* alatt megadhatod, hogy az AI heti menütervező kizárólag a **🔒 Saját receptjeidből**, vagy a **🌍 Közösségi nyilvános** és **🥑 Kifli.hu receptekből** is válogasson-e.

### 🔥 Kalória, Makrók & ±10%-os Napi Kalóriacél
* Minden receptnél tárolható (és **1 kattintással AI-val kiszámoltatható**) adagonkénti **kcal, fehérje (P), szénhidrát (CH) és zsír (Zs)**.
* **Napi kalóriacél (`Beállítások`):** Beállítható a kívánt napi kalóriakeret (pl. `1800 / 2000 / 2200 kcal/fő`), amit az AI menütervező **maximum ±10%-os eltéréssel** tart be minden napra, a heti menü napi kártyái pedig zöld/piros jelzéssel mutatják a napi összesítést.

### 🍲 Okos Heti Menütervező, Adagszám & Kifli Készlet-ellenőrzés
* **Teljesen testreszabható tervező (`Beállítások`):** Állítható a **háztartás mérete (1–12 fő)**, a **tervezett napok száma (1–7 nap)** és az **1 főtt étel hány napra készüljön (1–4 nap)**.
* **Élő Kifli készlet-ellenőrzés:** Heti menü generáláskor ellenőrzi a fő alapanyagok készletét a Kiflin — ami nincs raktáron, azt nem ajánlja fel arra a hétre.
* **💚 Healthy Score (1–5):** Minden receptnél állítható (*1 🍔 Kiadósabb → 5 💚 Szuper-fitt*), a heti menütervező pedig tartja a beállított heti átlagot.
* **✨ Szabályozható AI receptajánlások:** Ki/bekapcsolható, beállítható hány új ötletet (`1–5`) és melyik kategóriákba (`Reggeli / Ebéd / Vacsora`) tegyen be.
* **⚡ 0 AI-tokenes kézi csere & Reset:** Bármelyik étkezésre kattintva saját receptekből cserélhetsz több napra egyszerre, vagy 1 gombbal nullázhatod a heti menüt.

### 🏷️ 1-kattintásos Kifli Sajátmárka Optimalizáló + Kedvenc-védelem
* Az élő **🛒 Kosár** fülön 1 gombnyomásra megkeresi a drágább márkák olcsóbb **Kifli saját márkás** alternatíváit (*Miil, Moddia, Yutto, Ubomi, Dacello, Kitchin, Pappudia*).
* **Nem-kedvenc tételek:** azonnal, helyben lecseréli a Kifli kosaradban.
* **⭐ Kedvelt márkák védelme:** ami a kedvenceid között van, azt nem cseréli le a hátad mögött — egy átlátható **összehasonlító táblázat-popupban** mutatja meg a megtakarítást soronkénti és tömeges elfogadással.

### 🥗 Diéta, Allergén-helyettesítés, Büdzsé & Dedikált Kamra
* **Valódi laktózmentes & gluténmentes helyettesítés:** Kódszinten `laktózmentes` / `gluténmentes` keresőcímkét tesz az érintett alapanyagokra, és a sajátmárka-optimalizáló is csak mentes termékre cserélhet.
* **💰 Heti büdzsé-korlát (Ft):** Vizuális % sávval mutatja az élő kosárban, hol állsz a heti kerethez képest.
* **🧂 Dedikált Kamra fül:** Átláthatóan kezelhetőek az otthon mindig meglévő alapanyagok (só, bors, olaj, liszt…), amiket a bevásárlólista automatikusan kihagy, valamint a ⭐ kedvenc Kifli termékmárkák.

### 🧻 Anti-Loop Háztartási Lista & 🧠 Smart Restock
* Külön egyszeri lista tisztítószernek, papírzsepinek stb. opcionális pontos márkával.
* **3-lépcsős anti-loop állapotgép (`PENDING → IN_CART → ORDERED`):** Ami készlethiányos maradt, nem vész el; amit megrendeltél, végleg lezárul, így **soha nem loopol a következő héten**.
* **🧠 Smart Restock (0 AI token):** A Kifli rendelési előzményekből kiszámolja a fogyási ciklusokat, és 1 bökéssel visszateheted a listára, ami várhatóan elfogyott.

### 🔐 Többfelhasználós SaaS, Google Belépés & 1-Kattintásos Demo
* **Email + jelszó (`scrypt`) & Sign in with Google (OAuth 2.0)** + titkosított, felhasználónkénti **BYOK AI API kulcs** (Google Gemini / OpenAI / **Anthropic Claude** / Ollama).
* **1-kattintásos Demo fiók:** Teljesen elszigetelt, szimulált Kifli kosárral (`DemoCartSandbox`) és 0 AI-költségű bemutató móddal — regisztráció nélkül azonnal kipróbálható.
* **Hard Checkout fék:** Az AI soha nem ad le fizetős rendelést helyetted — csak összerakja a kosarat, te pedig átnézed és megrendeled a Kifli.hu-n.

### 📱 Privát Telegram Bot + Hétfő reggeli ütemezés
* Minden hétfőn 08:00-kor küldi a heti menüt Telegramon (`TELEGRAM_ALLOWED_USER_IDS` whitelisttel), természetes nyelven módosítható chatben, és **[✅ Megrendeltem]** gombbal üríti az egyszeri listát.

---

## 🚀 Gyors indítás (Linux szerver / NAS / Railway)

### Lokális / NAS Docker indítás
```bash
git clone https://github.com/bmark93/Kifli_Home.git
cd Kifli_Home
cp .env.example .env
# Szerkeszd a .env fájlt: GEMINI_API_KEY (vagy OPENAI_API_KEY), opcionálisan GOOGLE_CLIENT_ID / SECRET, TELEGRAM_BOT_TOKEN
docker compose up -d --build
```
Elérés belső hálón / VPN-en: 👉 `http://<szerver-ip>:8085`

### Railway (Publikus felhő deploy)
1. Kösd be a repót Railway-en (Settings → Source → Branch: `main` vagy `develop`).
2. **Fontos:** Adj hozzá egy **Persistent Volume**-ot **`/app/data`** mount path-ra, hogy az SQLite adatbázis, a feltöltött receptfotók, az AI kulcsok és a Kifli OAuth tokenek **minden deploy után megmaradjanak**!
3. Állítsd be a környezeti változókat: `AUTH_REQUIRED=1`, `APP_SECRET_KEY=<random>`, opcionálisan `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (callback URL: `https://<domain>/api/auth/google/callback`).

### Kifli.hu fiók összekötése (OAuth 2.1 PKCE — 1 perc, egyszer kell)
1. Nyisd meg a **⚙️ Beállítások** fület → **Kifli.hu fiók összekapcsolása**.
2. A felugró útmutatóban kattints az **„Értem, induljon a Kifli.hu belépés →”** gombra.
3. Belépés után a Kifli.hu a `http://localhost:3334/oauth/callback?code=...` címre irányít át (teljesen normális, ha a böngésző ekkor „Az oldal nem elérhető” hibát ír ki!).
4. Másold ki a böngésző címsorából a teljes linket és illeszd be a popup mezőjébe → **Összekapcsolás**. Innentől a program a háttérben **automatikusan megújítja** a tokeneket!

---

## 🔌 Saját beépített MCP Szerver (20 tool — Claude mobil app / Desktop)

Minden felhasználónak saját, privát **Streamable HTTP MCP végpontja** van (a *Beállítások* fülről 1 kattintással másolható):
```text
https://<domain>/mcp/<SAJAT_MCP_TOKEN>
```
A **Claude.ai → Settings → Connectors → Add custom connector** mezőbe beillesztve (Authentication: *None*) azonnal tudsz recepteket hozzáadni fotóval, makrókkal vagy módosítani a heti menüt közvetlenül a Claude mobil appból!

### Elérhető 20 MCP eszköz:
* **Receptek:** `list_recipes`, `upsert_recipe`, `delete_recipe`, `set_recipe_image`, `set_recipe_healthy_score`, `set_recipe_macros`, `set_recipe_visibility`
* **Heti menü:** `get_weekly_menu`, `set_weekly_meals`, `save_full_weekly_menu`, `reset_weekly_menu`, `add_extra_weekly_item`
* **Háztartás (Anti-Loop):** `list_household_items`, `add_household_item`, `delete_household_item`, `confirm_order_and_clear_household_items`
* **Bevásárlás & Preferenciák:** `get_aggregated_shopping_list`, `save_preferred_kifli_product`, `get_planner_settings`, `update_planner_settings`

