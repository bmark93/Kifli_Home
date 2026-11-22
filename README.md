# 🥐 Kifli Otthon — Privát Heti Menütervező & Kifli.hu MCP Asszisztens

Könnyűsúlyú, belső hálózaton / Tailscale VPN-en futtatható Dockeres alkalmazás Linux szerverre (és M4 MacBook Air teszteléshez).

## Mit tud az alaprendszer?

1. **Receptgyűjtemény (`reggeli`, `ebed`, `vacsora`):**
   - Egy recept több kategóriához is tartozhat (pl. rántotta = reggeli + vacsora).
   - Kézi felvétel + **1-kattintásos AI recept-import** URL-ből vagy bemásolt szövegből.
2. **Általános / Háztartási egyszeri lista (Anti-Loop védelemmel!):**
   - Külön kategória tisztítószernek, papírzsepinek stb., opcionális pontos márkával (pl. *„Zewa Deluxe”*, *„Domestos Pine”*).
   - **3-lépcsős állapotgép (`PENDING` -> `IN_CART` -> `ORDERED`):**
     - Amikor az AI sikeresen betette a Kifli kosárba, `IN_CART` státuszba kerül (ami készlethiány miatt nem ment be, marad `PENDING`!).
     - Amikor leadtad a rendelést, egyetlen érintéssel (Web UI vagy Telegram inline gomb) `ORDERED`-re zárul és eltűnik a listáról — **soha nem rendeli újra a következő héten!**
3. **Hivatalos Kifli.hu MCP integráció (`https://mcp.kifli.hu/mcp`):**
   - OAuth 2.1 (PKCE) bejelentkezés automatikus háttérbeli refresh-token megújítással (jelszót soha nem tárol!).
   - **Hard Checkout fék:** az AI kizárólag a kosaradat rakhatja össze, fizetést/rendelést soha nem küld el helyetted.
   - **Kamra-alapanyagok kihagyása** (só, bors, olaj, liszt stb.) + **Kedvenc Kifli termékek memóriája** + **Mennyiség-összevonás**.
4. **Hétfő reggeli értesítés & Természetes nyelvű Chat (Web + Privát Telegram Bot):**
   - Minden hétfőn 08:00-kor összeállítja a heti menüt a receptjeidből + **1 db új receptajánlást**, és elküldi Telegramon.
   - Simán visszaírhatsz neki: *„Oké, de kedd ebédre inkább krumplifőzeléket kívántam meg, adj hozzá még 2 tejet mert most jutott eszembe, és készítsd el a Kifli kosaramat!”*
5. **Filléres, privát LLM motor (`~30–150 Ft / hó`):**
   - Egyetlen `.env` kapcsolóval megy **Google Gemini 2.5 Flash** (`LLM_PROVIDER=gemini`) vagy **OpenAI `gpt-4.1-mini`** (`LLM_PROVIDER=openai`) fizetős API kulccsal (egyik sem tanít az API-n küldött adataidon), vagy lokális M4 MacBook Air Ollama-val (`LLM_PROVIDER=custom`).

---

## Gyors indítás (Linux szerveren vagy M4 MacBook Air-en)

```bash
cp .env.example .env
# Szerkeszd a .env fájlt: add meg a GEMINI_API_KEY (vagy OPENAI_API_KEY) kulcsot,
# és opcionálisan a TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USER_IDS értékeket!

docker compose up -d --build
```

Ezután nyisd meg belső hálón / VPN-en:
👉 `http://<linux-szerver-ip>:8085`

### Kifli.hu fiók összekötése (1 perc, egyszer kell megcsinálni)
1. Menj a **🔐 Kifli MCP & Kamra** fülre (vagy írd be Telegramon: `/kifli_login`).
2. Kattints az **1. Kifli belépési link kérése** gombra, és lépj be a `identity.kifli.hu` oldalon.
3. A böngésző átirányít egy `http://localhost:3334/oauth/callback?code=...` címre (teljesen normális, ha azt írja, hogy *„Az oldal nem érhető el”*).
4. Másold ki a böngésző címsorából a **teljes URL-t**, illeszd be a **2. Mentés** mezőbe, és kész — innentől a tokenek a `./data/kifli_oauth/` alatt automatikusan frissülnek!

---

## 🔌 Saját beépített MCP Szerver (Claude Desktop / Claude Code / M4 MacBook Air)

Az alkalmazás saját **Streamable HTTP MCP végpontot** is publikál ugyanazon a porton:
👉 `http://<linux-szerver-ip>:8085/mcp`

Így a saját **Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`) vagy bármilyen MCP kliens közvetlenül tud recepteket felvenni/szerkeszteni, heti menüt összeállítani és háztartási listát kezelni **0 Ft extra AI API költséggel**:

```json
{
  "mcpServers": {
    "kifli-otthon": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://<linux-szerver-ip>:8085/mcp",
        "--allow-http"
      ]
    }
  }
}
```
*(Ha `APP_ACCESS_PIN` be van állítva a `.env`-ben, add hozzá az URL végéhez: `?pin=A_PIN_KODOD` vagy fejlécben `Authorization: Bearer A_PIN_KODOD`.)*
