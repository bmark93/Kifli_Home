from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import Settings
from app.db import DAYS_HU, Database
from app.kifli_mcp import KifliMCPManager

log = logging.getLogger("kifli_otthon.agent")

SYSTEM_PROMPT_HU = """Te vagy az otthoni privát Séf és Kifli.hu Bevásárló-Asszisztens.
Mindig természetes, barátságos, tömör magyar nyelven válaszolj (tegeződve).

FŐ SZABÁLYOK ÉS MŰKÖDÉS:
1. KATEGÓRIÁK, KÉSZLET-ELLENŐRZÉS ÉS HEALTHY SCORE A HETI MENÜBEN:
   - A receptek 3 étkezési kategóriába tartozhatnak: `reggeli`, `ebed`, `vacsora`, és mindegyikhez tartozik egy `healthy_score` (1 = bűnözős/nehéz .. 5 = szuper-egészséges).
   - Amikor heti menüt tervezel (Hétfő–Vasárnap, napi 3 étkezés):
     * **KÖTELEZŐ KIFLI KÉSZLET-ELLENŐRZÉS:** Ha a Kifli MCP aktív, mielőtt elmented a menüt, ellenőrizd a `kifli__batch_search_products` eszközzel a kiszemelt receptek kulcsfontosságú/szezonális/speciális alapanyagait (pl. frankfurti levesnél a *kelkáposzta*, halas ételnél a hal, speciális zöldségek/gyümölcsök)! **Ha egy étel kulcs-alapanyaga jelenleg NINCS készleten vagy nem kapható a Kiflin, azt a receptet NE ajánld fel erre a hétre** — válassz helyette másik receptet, aminek minden fő hozzávalója elérhető! Ha emiatt kihagytál egy receptet, röviden jelezd a válaszodban!
     * **KIEGYENSÚLYOZOTT HEALTHY SCORE:** Figyelj rá, hogy a heti menü egészségesen kiegyensúlyozott legyen (a heti átlag `healthy_score` legyen legalább **3.3–3.5**)! Ne tegyél egymás után több 1–2-es nehéz ételt — ha az ebéd 2-es házias fogás, a reggeli vagy vacsora legyen 4–5-ös könnyű/egészséges!
     * Válogass változatosan a mentett receptekből (egy nagyobb főzős ebéd nyugodtan szerepelhet 2 egymást követő napon is, hogy praktikus és olcsó legyen!).
     * Kötelezően tegyél bele **+1 db ÚJ receptajánlást** (`is_recommendation: true`, egy olyan finom és lehetőleg 4–5 healthy score-os ételt, ami még nincs a saját receptek között, a hozzávalói pedig tényleg kaphatók a Kiflin — töltsd ki hozzá a `custom_ingredients` hozzávalókat!).
     * Mindig mentsd el a kész tervet a `save_full_weekly_plan` eszközzel!
     * A javaslat végén mindig sorold fel az Általános / Háztartási listán szereplő `PENDING` tételeket is!

2. BESZÉLGETŐS MÓDOSÍTÁSOK:
   - Ha a felhasználó menet közben módosít (pl. "inkább krumplifőzeléket kívántam meg kedden, és adj hozzá még 2 tejet mert most jutott eszembe"):
     * Cseréld le az adott étkezést az `update_meal_slot` eszközzel (ha nincs ilyen recept elmentve, állítsd össze te a pontos `custom_ingredients` listáját autentikus magyar konyhai alapanyagokkal — pl. a finomfőzelék zöldborsóból, sárgarépából és karalábéból készül tejjel/liszttel, nem sárgaborsóból!).
     * Ha a felhasználó kéri, hogy vedd is fel a receptek közé ("vedd fel receptbe", "mentsd el"), akkor KÖTELEZŐEN hívd meg rá a `save_recipe_to_db` eszközt is, és az így kapott `recipe_id`-t használd a menüben!
     * A menet közben kért extra egyszeri élelmiszert (pl. "+2 tej") vedd fel az `add_adhoc_shopping_item` eszközzel (ha háztartási/tisztítószer jellegű, akkor az `add_general_household_item` eszközzel).

3. KIFLI.HU KOSÁR ÖSSZEÁLLÍTÁSA ÉS ANTI-LOOP VÉDELEM:
   - Amikor a felhasználó kéri a Kifli kosár összeállítását:
     1) Először hívd meg a `get_aggregated_shopping_list` eszközt! Ez visszaadja az összevont recept+adhoc hozzávalókat, az Általános `PENDING` listát (`general_item_id`-val és esetleges `brand_hint` márkával), a mentett kedvenc Kifli termékeket (`preferred_kifli_product`), és a kamra-alapanyagokat (`staples_assumed_at_home`).
     2) A `staples_assumed_at_home` (pl. só, bors, olaj, liszt, pirospaprika) elemeket NE tedd be automatikusan a Kifli kosárba, csak a válaszod végén kérdezz rá egy sorban, hogy van-e otthon belőlük!
     3) Használd a `kifli__batch_search_products` (egyszerre max 4 keresőkifejezés hívásonként; nyugodtan adj ki több párhuzamos tool-hívást egy körben!) és a `kifli__add_items_to_cart` eszközöket! Ha van `preferred_kifli_product` vagy `brand_hint` (pl. pontos tisztítószer márka), elsősorban azt keresd. Csak valós, MCP által visszaadott `productId`-ra hagyatkozz!
     4) KRITIKUS KISZERELÉS / DARABSZÁM SZABÁLY: A `kifli__add_items_to_cart` `quantity` mezője CSOMAG / DARAB számot vár, NEM grammot! Például:
        - Ha a listán `480 g zabpehely` szerepel, és a Kifli termék `500 g`-os csomag, akkor `quantity: 1` (1 csomag!), SOHA NE `480`!
        - Ha `30 db tojás` kell, és `10 db`-os dobozt találsz, akkor `quantity: 3` (3 doboz), SOHA NE `30`!
        - Ha `1.6 l tej` kell, és `1 l`-es dobozt találsz, akkor `quantity: 2` (felfelé kerekítve egész csomagra)!
     5) KRITIKUS ANTI-LOOP SZABÁLY: Miután betetted a tételeket a Kifli kosárba, azokra az Általános (`general_pending_items`) tételekre, amelyeket **SIKERESEN** betettél a kosárba, KÖTELEZŐEN hívd meg a `mark_general_items_placed_in_cart` eszközt! Amelyik tételt készlethiány vagy hiba miatt NEM sikerült kosárba tenni, arra NE hívd meg (hogy `PENDING` maradjon), és szólj róla a felhasználónak!
     6) SOHA ne adj le végleges/fizetős rendelést — csak a kosarat állítsd össze, írd meg tételesen mit és hány csomaggal tettél be (és a kosár végösszegét a `kifli__get_cart` alapján), hogy a felhasználó a Kifli.hu oldalon vagy appban ellenőrizhesse és megrendelhesse!
"""


LOCAL_TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_saved_recipes",
            "description": "Kilistázza az adatbázisban elmentett saját recepteket hozzávalókkal (opcionálisan szűrve: reggeli, ebed, vacsora).",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Opcionális szűrő: reggeli, ebed, vagy vacsora",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_recipe_to_db",
            "description": "Új recept mentése VAGY meglévő recept frissítése (ha megadod a recipe_id-t) a saját receptgyűjteményben strukturált hozzávalókkal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipe_id": {
                        "type": "integer",
                        "description": "Opcionális: ha meglévő receptet szerkesztesz/módosítasz, add meg az ID-ját!",
                    },
                    "title": {"type": "string", "description": "A recept neve"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Kategóriák listája: reggeli, ebed, vacsora",
                    },
                    "servings": {"type": "integer", "description": "Adagszám (pl. 2 vagy 4)"},
                    "healthy_score": {
                        "type": "integer",
                        "description": "Egészségességi pontszám 1 (nehéz/bűnözős) és 5 (szuper-egészséges) között",
                    },
                    "instructions": {"type": "string", "description": "Rövid elkészítési leírás"},
                    "ingredients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string"},
                                "is_staple": {"type": "boolean"},
                                "brand_hint": {"type": "string"},
                            },
                            "required": ["name", "quantity", "unit"],
                        },
                    },
                },
                "required": ["title", "categories", "ingredients"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_weekly_plan",
            "description": "Lekéri az aktuális heti menütervet, extra tételeket és az Általános/Háztartási listát.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_full_weekly_plan",
            "description": "Elmenti a teljes heti (hetfo..vasarnap, reggeli/ebed/vacsora) menütervet és a +1 ajánlás megjegyzését.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recommendation_note": {
                        "type": "string",
                        "description": "Rövid indoklás, mi a heti +1 új receptajánlás és miért",
                    },
                    "slots": {
                        "type": "array",
                        "description": "A heti étkezések listája (hetfo, kedd, szerda, csutortok, pentek, szombat, vasarnap x reggeli, ebed, vacsora)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "day": {
                                    "type": "string",
                                    "description": "hetfo | kedd | szerda | csutortok | pentek | szombat | vasarnap",
                                },
                                "meal_type": {
                                    "type": "string",
                                    "description": "reggeli | ebed | vacsora",
                                },
                                "title": {"type": "string"},
                                "recipe_id": {
                                    "type": "integer",
                                    "description": "Ha saját mentett receptből van, annak az ID-ja (különben hagyd ki)",
                                },
                                "is_recommendation": {
                                    "type": "boolean",
                                    "description": "True pontosan a heti +1 új ajánlásnál",
                                },
                                "custom_ingredients": {
                                    "type": "array",
                                    "description": "Kötelező kitölteni, ha nincs recipe_id (pl. a +1 új ajánlásnál)!",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "quantity": {"type": "number"},
                                            "unit": {"type": "string"},
                                            "is_staple": {"type": "boolean"},
                                        },
                                        "required": ["name", "quantity", "unit"],
                                    },
                                },
                            },
                            "required": ["day", "meal_type", "title"],
                        },
                    },
                },
                "required": ["slots"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_meal_slot",
            "description": "Egyetlen nap egyetlen étkezésének lecserélése (pl. 'kedd ebédre krumplifőzeléket kívántam meg').",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {
                        "type": "string",
                        "description": "hetfo | kedd | szerda | csutortok | pentek | szombat | vasarnap",
                    },
                    "meal_type": {"type": "string", "description": "reggeli | ebed | vacsora"},
                    "title": {"type": "string", "description": "Az új étel neve"},
                    "recipe_id": {
                        "type": "integer",
                        "description": "Mentett recept ID, ha létezik az adatbázisban",
                    },
                    "custom_ingredients": {
                        "type": "array",
                        "description": "Ha nincs elmentve ez a recept, add meg a hozzávalóit, hogy bekerüljön a bevásárlólistába!",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "number"},
                                "unit": {"type": "string"},
                                "is_staple": {"type": "boolean"},
                            },
                            "required": ["name", "quantity", "unit"],
                        },
                    },
                },
                "required": ["day", "meal_type", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_adhoc_shopping_item",
            "description": "Menet közben eszébe jutott egyszeri tétel hozzáadása az eheti bevásárláshoz (pl. '+2 liter tej').",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "brand_hint": {"type": "string"},
                },
                "required": ["name", "quantity", "unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_general_household_item",
            "description": "Tétel felvétele az Általános / Háztartási (tisztítószer, papírzsepi stb.) egyszeri listára opcionális márkával.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Pl. papírzsepi, vízkőoldó, mosogatógép kapszula"},
                    "quantity": {"type": "number"},
                    "unit": {"type": "string"},
                    "brand_hint": {"type": "string", "description": "Opcionális pontos márka, pl. Zewa Deluxe vagy Domestos Pine"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aggregated_shopping_list",
            "description": "Összesíti a heti menü összes hozzávalóját + az adhoc tételeket + az Általános PENDING listát, szétválasztva a kamra-alapanyagokat.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_general_items_placed_in_cart",
            "description": "Átállítja IN_CART státuszra azokat az Általános listás tételeket, amiket SIKERESEN betettél a Kifli kosárba.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "general_item_id": {"type": "integer"},
                                "kifli_product_id": {"type": "string"},
                                "kifli_product_name": {"type": "string"},
                            },
                            "required": ["general_item_id"],
                        },
                    }
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_order_and_clear_general_items",
            "description": "Amikor a felhasználó jelzi, hogy megrendelte a Kifli kosarat: végleg törli/ORDERED-re zárja a kosárba tett Általános tételeket, hogy ne loopoljanak!",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_pending": {
                        "type": "boolean",
                        "description": "True csak akkor, ha kifejezetten az összes általános tétel törlését kérte",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_preferred_kifli_product",
            "description": "Elmenti a felhasználó kedvenc Kifli termékét egy alapanyaghoz (pl. tej -> konkrét Kifli termék ID és név).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ingredient_name": {"type": "string"},
                    "kifli_product_id": {"type": "string"},
                    "kifli_product_name": {"type": "string"},
                },
                "required": ["ingredient_name", "kifli_product_id", "kifli_product_name"],
            },
        },
    },
]


class ChefShoppingAgent:
    def __init__(self, settings: Settings, db: Database, kifli: KifliMCPManager) -> None:
        self.settings = settings
        self.db = db
        self.kifli = kifli

    def _create_client(self) -> AsyncOpenAI:
        if not self.settings.llm_api_key or "IDE_JON" in self.settings.llm_api_key:
            raise RuntimeError(
                f"Hiányzik az API kulcs a .env fájlból (LLM_PROVIDER={self.settings.llm_provider})!"
            )
        kwargs: dict[str, Any] = {
            "api_key": self.settings.llm_api_key,
            "timeout": 40.0,
            "max_retries": 1,
        }
        if self.settings.llm_base_url:
            kwargs["base_url"] = self.settings.llm_base_url
        return AsyncOpenAI(**kwargs)

    async def _chat_completion(
        self,
        client: AsyncOpenAI,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> Any:
        candidates = [self.settings.llm_model]
        if self.settings.llm_provider == "gemini":
            for fallback_m in ("gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash-lite"):
                if fallback_m not in candidates:
                    candidates.append(fallback_m)

        last_err: Exception | None = None
        for mdl in candidates:
            try:
                call_kwargs: dict[str, Any] = {
                    "model": mdl,
                    "messages": messages,
                    "temperature": temperature,
                }
                if tools:
                    call_kwargs["tools"] = tools
                return await client.chat.completions.create(**call_kwargs)
            except Exception as exc:
                last_err = exc
                log.warning("LLM hívás hiba (%s), próba a következővel ha van: %s", mdl, exc)
        assert last_err is not None
        raise last_err

    async def _build_all_tools(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        tools = list(LOCAL_TOOLS_SPEC)
        mcp_map: dict[str, str] = {}
        try:
            kifli_tools = await self.kifli.list_tools()
            for kt in kifli_tools:
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": kt["llm_name"],
                            "description": kt["description"],
                            "parameters": kt["parameters"],
                        },
                    }
                )
                mcp_map[kt["llm_name"]] = kt["mcp_name"]
        except Exception as exc:
            log.warning("Kifli MCP tool lista nem érhető el (folytatás helyi eszközökkel): %s", exc)
        return tools, mcp_map

    async def _execute_local_tool(self, name: str, args: dict[str, Any]) -> Any:
        if name == "list_saved_recipes":
            return self.db.list_recipes(category=args.get("category"))

        if name == "save_recipe_to_db":
            return self.db.create_or_update_recipe(
                recipe_id=args.get("recipe_id"),
                title=args["title"],
                categories=args.get("categories", ["ebed"]),
                ingredients=args.get("ingredients", []),
                servings=int(args.get("servings", 2)),
                instructions=args.get("instructions", ""),
                healthy_score=int(args.get("healthy_score", 3) or 3),
            )

        if name == "get_current_weekly_plan":
            return {
                "weekly_plan": self.db.get_weekly_plan(),
                "general_items": self.db.list_general_items(include_ordered=False),
            }

        if name == "save_full_weekly_plan":
            days_struct: dict[str, dict[str, Any]] = {d[0]: {} for d in DAYS_HU}
            for slot in args.get("slots", []):
                dkey = slot["day"].strip().lower()
                mkey = slot["meal_type"].strip().lower()
                if dkey in days_struct:
                    days_struct[dkey][mkey] = {
                        "title": slot["title"],
                        "recipe_id": slot.get("recipe_id"),
                        "is_recommendation": bool(slot.get("is_recommendation", False)),
                        "custom_ingredients": slot.get("custom_ingredients") or [],
                    }
            return self.db.save_weekly_plan(
                days=days_struct,
                recommendation_note=args.get("recommendation_note", ""),
            )

        if name == "update_meal_slot":
            return self.db.update_weekly_meal_slot(
                day_key=args["day"],
                meal_type=args["meal_type"],
                title=args["title"],
                recipe_id=args.get("recipe_id"),
                custom_ingredients=args.get("custom_ingredients"),
            )

        if name == "add_adhoc_shopping_item":
            return self.db.add_adhoc_item_to_week(
                name=args["name"],
                quantity=float(args.get("quantity", 1)),
                unit=args.get("unit", "db"),
                brand_hint=args.get("brand_hint", ""),
            )

        if name == "add_general_household_item":
            return self.db.add_general_item(
                name=args["name"],
                quantity=float(args.get("quantity", 1)),
                unit=args.get("unit", "db"),
                brand_hint=args.get("brand_hint", ""),
            )

        if name == "get_aggregated_shopping_list":
            return self.db.aggregate_shopping_list()

        if name == "mark_general_items_placed_in_cart":
            mapped = [
                {
                    "id": item["general_item_id"],
                    "kifli_product_id": item.get("kifli_product_id", ""),
                    "kifli_product_name": item.get("kifli_product_name", ""),
                }
                for item in args.get("items", [])
            ]
            return self.db.mark_general_items_in_cart(mapped)

        if name == "confirm_order_and_clear_general_items":
            return self.db.finalize_order_and_clear_general_items(
                include_pending_if_forced=bool(args.get("include_pending", False))
            )

        if name == "remember_preferred_kifli_product":
            return self.db.save_product_preference(
                ingredient_name=args["ingredient_name"],
                kifli_product_id=args["kifli_product_id"],
                kifli_product_name=args["kifli_product_name"],
            )

        raise ValueError(f"Ismeretlen helyi tool: {name}")

    async def chat(self, user_message: str, source: str = "web") -> str:
        client = self._create_client()
        history = self.db.get_recent_chat_messages(limit=12)
        self.db.add_chat_message("user", user_message, source=source)

        kifli_status = await self.kifli.get_status()
        status_hint = (
            "Kifli.hu MCP kapcsolat: AKTÍV (tudsz keresni és kosarat építeni)."
            if kifli_status["authenticated"]
            else "Kifli.hu MCP kapcsolat: NINCS BEJELENTKEZVE (menüt és listát tudsz tervezni, de a kosárba rakáshoz kérd meg a felhasználót, hogy lépjen be a Kifli MCP fülön)."
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT_HU}\n\n[{status_hint}]"},
        ]
        for h in history:
            if h["role"] in ("user", "assistant"):
                messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        tools, mcp_map = await self._build_all_tools()

        for _step in range(24):
            resp = await self._chat_completion(
                client=client,
                messages=messages,
                tools=tools,
                temperature=0.3,
            )
            choice = resp.choices[0].message
            tool_calls = choice.tool_calls or []

            if not tool_calls:
                reply_text = (choice.content or "").strip() or "Kész!"
                self.db.add_chat_message("assistant", reply_text, source=source)
                return reply_text

            # Gemini 3.x megköveteli az extra_content (thought_signature) visszaadását a tool_calls üzenetben!
            assistant_dump = choice.model_dump(exclude_none=True)
            assistant_dump.setdefault("content", "")
            messages.append(assistant_dump)

            for tc in tool_calls:
                fn_name = tc.function.name
                try:
                    parsed_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed_args = {}

                try:
                    if fn_name in mcp_map:
                        raw_out = await self.kifli.call_tool(mcp_map[fn_name], parsed_args)
                        tool_output = raw_out
                    else:
                        res = await self._execute_local_tool(fn_name, parsed_args)
                        tool_output = json.dumps(res, ensure_ascii=False)
                except Exception as exc:
                    log.exception("Hiba a(z) %s tool futtatásakor", fn_name)
                    tool_output = json.dumps({"error": str(exc)}, ensure_ascii=False)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    }
                )

        fallback = "Elértem a maximális eszközlépés-számot, kérlek ellenőrizd a kosarat vagy pontosíts!"
        self.db.add_chat_message("assistant", fallback, source=source)
        return fallback

    async def generate_monday_weekly_proposal(self) -> str:
        prompt = (
            "Készíts nekünk egy friss heti menütervezetet erre a hétre (Hétfőtől Vasárnapig: reggeli, ebéd, vacsora)! "
            "1) Nézd meg a mentett receptjeinket (`list_saved_recipes` — nézd a `healthy_score` értékeket is!) és az Általános/Háztartási listánkat (`get_current_weekly_plan`). "
            "2) Ha a Kifli MCP be van jelentkezve, KÖTELEZŐEN ellenőrizd a `kifli__batch_search_products` eszközzel a kiszemelt receptek fő/szezonális alapanyagait (pl. kelkáposzta, friss hal, speciális zöldség): ha egy fő hozzávaló NINCS készleten a Kiflin, NE ajánld fel azt az ételt erre a hétre! "
            "3) Állítsd össze a heti menüt kiegyensúlyozott `healthy_score` elosztással (heti átlag >= 3.3, váltogasd a könnyű 4–5-ös és a házias 2–3-as ételeket) + pontosan 1 db izgalmas ÚJ receptajánlással (`is_recommendation=true`, kitöltött `custom_ingredients`-szel, aminek minden hozzávalója kapható a Kiflin), és mentsd el a `save_full_weekly_plan` eszközzel! "
            "4) Köszönj nekünk, mutasd be áttekinthetően a heti menüt (röviden jelezve a heti átlag healthy score-t és ha valamit készlethiány miatt ki kellett hagyni), emeld ki a 🌟 +1 ajánlást, sorold fel mi van az 🧻 Általános listán, és kérdezd meg: 'Mit szólsz hozzá? Módosítsunk valamin, vagy összerakhatom a Kifli kosarat?'"
        )
        return await self.chat(prompt, source="scheduler")

    async def parse_recipe_from_text_or_url(self, text_or_url: str) -> dict[str, Any]:
        """URL vagy bemásolt szöveg alapján strukturált receptet nyer ki és elmenti."""
        raw_content = text_or_url.strip()
        source_url = ""
        if raw_content.startswith(("http://", "https://")) and "\n" not in raw_content:
            source_url = raw_content
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
                r = await http.get(source_url, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                raw_content = r.text[:25000]

        client = self._create_client()
        extract_prompt = (
            "Nyerj ki az alábbi szövegből/HTML-ből egyetlen receptet szigorúan JSON formátumban!\n"
            "Sémanév-kulcsok:\n"
            '{"title": "...", "categories": ["reggeli"|"ebed"|"vacsora"], "servings": 2, "healthy_score": 3, '
            '"instructions": "rövid magyar összefoglaló", '
            '"ingredients": [{"name": "...", "quantity": 1.0, "unit": "g|dkg|kg|ml|dl|l|db|ek|tk|csipet", "is_staple": false}]}\n\n'
            f"Forrás:\n{raw_content}"
        )
        resp = await self._chat_completion(
            client=client,
            messages=[
                {"role": "system", "content": "Csak érvényes JSON objektummal válaszolj, markdown keret nélkül."},
                {"role": "user", "content": extract_prompt},
            ],
            temperature=0.1,
        )
        txt = (resp.choices[0].message.content or "{}").strip()
        if txt.startswith("```"):
            txt = txt.strip("`")
            if txt.startswith("json"):
                txt = txt[4:].strip()
        parsed = json.loads(txt)
        return self.db.create_or_update_recipe(
            title=parsed.get("title", "Importált recept"),
            categories=parsed.get("categories", ["ebed"]),
            servings=int(parsed.get("servings", 2)),
            healthy_score=int(parsed.get("healthy_score", 3) or 3),
            instructions=parsed.get("instructions", ""),
            source_url=source_url,
            ingredients=parsed.get("ingredients", []),
        )
