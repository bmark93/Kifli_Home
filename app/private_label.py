from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.db import Database, detect_diet_requirements, normalize_key
from app.kifli_mcp import KifliMCPManager
from app.llm_agent import ChefShoppingAgent

log = logging.getLogger("kifli_otthon.private_label")

# Hivatalos Kifli.hu / Rohlik Group saját márkák
KIFLI_PRIVATE_LABEL_BRANDS = {
    "miil",
    "moddia",
    "yutto",
    "ubomi",
    "dacello",
    "kitchin",
    "pappudia",
    "fjoru",
    "fjor",
    "masna",
    "maso!",
    "sutis",
    "pauw",
    "bambini",
    "soltino",
    "marks & spencer",
    "kifli",
    "rohlik",
}


def is_kifli_private_label(name: str, brand: str = "") -> bool:
    b = (brand or "").strip().lower()
    if b in KIFLI_PRIVATE_LABEL_BRANDS:
        return True
    n_low = (name or "").strip().lower()
    return any(
        n_low.startswith(pl + " ") or f" {pl} " in n_low
        for pl in ("miil", "moddia", "yutto", "ubomi", "dacello", "kitchin", "pappudia")
    )


def extract_favorite_product_ids(
    db: Database, kifli_favorites_raw: str | None = None
) -> tuple[set[int], set[str]]:
    """
    Összegyűjti a kedvenc termékeket két forrásból:
    1. Helyi `product_preferences` tábla (product_id + alapanyag-kulcsok)
    2. Kifli.hu `get_all_user_favorites` (ha van)
    """
    fav_ids: set[int] = set()
    fav_labels: set[str] = set()

    for pref in db.list_product_preferences():
        pid_str = str(pref.get("kifli_product_id") or "").strip()
        if pid_str.isdigit():
            fav_ids.add(int(pid_str))
        if pref.get("kifli_product_name"):
            fav_labels.add(normalize_key(pref["kifli_product_name"]))

    if kifli_favorites_raw:
        try:
            payload = json.loads(kifli_favorites_raw)
            data = payload.get("data")
            items: list[Any] = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("products") or data.get("items") or []
            for it in items:
                if isinstance(it, dict):
                    pid = it.get("productId") or it.get("id")
                    if pid is not None and str(pid).isdigit():
                        fav_ids.add(int(pid))
        except Exception:
            pass

    return fav_ids, fav_labels


def split_auto_vs_favorite_swaps(
    candidates: list[dict[str, Any]],
    fav_ids: set[int],
    fav_labels: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Szétválasztja a validált, olcsóbb Kifli saját márkás cseréket:
    - auto_swaps: NEM kedvenc -> azonnal kicserélhető a kosárban
    - favorite_proposals: KEDVENC -> popupban megkérdezzük a felhasználót!
    """
    auto_swaps: list[dict[str, Any]] = []
    favorite_proposals: list[dict[str, Any]] = []

    for c in candidates:
        old_id = int(c["old_product_id"])
        old_name_norm = normalize_key(c.get("old_name", ""))
        savings = int(c.get("savings_ft", 0))
        if savings < 20:
            continue
        is_fav = (old_id in fav_ids) or (old_name_norm in fav_labels) or bool(c.get("is_favorite"))
        if is_fav:
            favorite_proposals.append(c)
        else:
            auto_swaps.append(c)

    return auto_swaps, favorite_proposals


def _parse_json_from_llm(raw_text: str) -> Any:
    txt = (raw_text or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.startswith("json"):
            txt = txt[4:].strip()
    return json.loads(txt)


async def optimize_cart_private_label_structured(
    db: Database,
    kifli: KifliMCPManager,
    agent: ChefShoppingAgent,
    parsed_cart: dict[str, Any],
) -> dict[str, Any]:
    """
    Valódi, kétlépcsős Kifli sajátmárka-optimalizálás:
    1. Nem-kedvenc tételek: AZONNALI tényleges csere a Kifli kosárban (MCP remove + add).
    2. Kedvenc tételek: NEM nyúl hozzájuk, visszaküldi strukturáltan a popup ablaknak!
    """
    cart_items = parsed_cart.get("items") or []
    if not cart_items:
        return {
            "auto_swapped": [],
            "auto_savings_ft": 0,
            "favorite_proposals": [],
            "message": "A Kifli kosarad jelenleg üres.",
        }

    # 1. Kedvencek begyűjtése (helyi + Kifli.hu)
    kifli_fav_raw = None
    try:
        kifli_fav_raw = await kifli.call_tool_untruncated(
            "get_all_user_favorites",
            {"context": "Check user favorites before private-label cart optimization"},
        )
    except Exception:
        pass
    fav_ids, fav_labels = extract_favorite_product_ids(db, kifli_fav_raw)

    # Csak a még NEM Kifli saját márkás tételeket vizsgáljuk
    eligible_items = [
        it for it in cart_items if not is_kifli_private_label(it.get("name", ""))
    ]
    if not eligible_items:
        return {
            "auto_swapped": [],
            "auto_savings_ft": 0,
            "favorite_proposals": [],
            "message": "A kosaradban már minden tétel Kifli saját márkás (vagy optimális)! 🎉",
        }

    client = agent._create_client()
    ps = db.get_planner_settings()
    active_allergens = ps.get("allergens") or []
    allergen_note = ""
    if active_allergens:
        allergen_note = (
            f"AKTÍV DIÉTA/ALLERGÉNEK: {', '.join(active_allergens)}! "
            "Ha 'laktóz' aktív, tejtermékhez KIZÁRÓLAG 'laktózmentes' Kifli saját márkás terméket keress és válassz (soha ne sima tejterméket!). "
            "Ha 'glutén' aktív, tésztához/kenyérhez KIZÁRÓLAG 'gluténmentes' változatot!"
        )

    # 2. LLM 1. villámhívás: minden vizsgált termékhez 1 rövid magyar Kifli sajátmárka keresőkifejezés
    items_brief = [
        {
            "old_product_id": it["product_id"],
            "name": it["name"],
            "category": it["category"],
            "quantity": it["quantity"],
            "unit_price_ft": it["unit_price"],
            "line_total_ft": it["line_total"],
            "volume": it["volume"],
            "unit": it["unit"],
            "required_diet_tags": detect_diet_requirements(it["name"], active_allergens),
        }
        for it in eligible_items
    ]

    kw_prompt = (
        "Az alábbi Kifli.hu kosár-tételekhez adj meg 1-1 rövid magyar keresőkifejezést, amivel a Kifli.hu-n "
        "megtalálható a hozzájuk passzoló Kifli saját márkás (Miil, Moddia, Yutto, Ubomi, Dacello, Kitchin, Pappudia) "
        "alternatíva! Ha `required_diet_tags` tartalmaz 'laktózmentes' vagy 'gluténmentes' jelzőt, azt KÖTELEZŐEN írd bele a kulcsszóba (pl. 'Miil laktózmentes tejföl')! "
        "Ha egy tételhez (pl. friss zöldség/gyümölcs/speciális vegyszer) nincs Kifli saját márka, hagyd ki.\n"
        f"{allergen_note}\n"
        'Válaszolj SZIGORÚAN JSON tömbbel: [{"old_product_id": 123, "keyword": "Miil laktózmentes tej"}]\n\n'
        f"Kosár tételek:\n{json.dumps(items_brief, ensure_ascii=False)}"
    )
    kw_resp = await agent._chat_completion(
        client=client,
        messages=[
            {"role": "system", "content": "Csak érvényes JSON tömbbel válaszolj, magyarázat nélkül."},
            {"role": "user", "content": kw_prompt},
        ],
        temperature=0.1,
    )
    try:
        kw_list = _parse_json_from_llm(kw_resp.choices[0].message.content or "[]")
    except Exception as exc:
        log.warning("Private label keyword JSON parse hiba: %s", exc)
        kw_list = []

    if not kw_list:
        return {
            "auto_swapped": [],
            "auto_savings_ft": 0,
            "favorite_proposals": [],
            "message": "Nem találtam olcsóbb Kifli saját márkás helyettesítőt a kosaradban lévő tételekhez.",
        }

    # 3. Párhuzamos Kifli MCP batch_search_products (max 4 query / hívás)
    chunks = [kw_list[i : i + 4] for i in range(0, len(kw_list), 4)]

    async def _search_chunk(chunk: list[dict[str, Any]]) -> list[tuple[int, list[dict[str, Any]]]]:
        queries = [{"keyword": str(c["keyword"])} for c in chunk if c.get("keyword")]
        if not queries:
            return []
        try:
            raw = await kifli.call_tool_untruncated(
                "batch_search_products",
                {
                    "queries": queries,
                    "context": "Find Kifli private-label alternatives for cart items",
                },
            )
            data = json.loads(raw)
            results = data.get("results") or []
            out: list[tuple[int, list[dict[str, Any]]]] = []
            for idx, res in enumerate(results):
                if idx >= len(chunk):
                    break
                old_pid = int(chunk[idx]["old_product_id"])
                prods = res.get("products") or []
                # Csak raktáron lévő Kifli saját márkás jelöltek!
                pl_prods = [
                    p
                    for p in prods
                    if p.get("inStock", True)
                    and is_kifli_private_label(p.get("productName", ""), p.get("brand", ""))
                ][:5]
                out.append((old_pid, pl_prods))
            return out
        except Exception as exc:
            log.warning("Private label batch_search hiba: %s", exc)
            return []

    chunk_results = await asyncio.gather(*[_search_chunk(ch) for ch in chunks])
    candidates_by_old: dict[int, list[dict[str, Any]]] = {}
    valid_new_products: dict[int, dict[str, Any]] = {}
    for batch in chunk_results:
        for old_pid, pl_prods in batch:
            if pl_prods:
                candidates_by_old[old_pid] = pl_prods
                for p in pl_prods:
                    valid_new_products[int(p["productId"])] = p

    if not candidates_by_old:
        return {
            "auto_swapped": [],
            "auto_savings_ft": 0,
            "favorite_proposals": [],
            "message": "Jelenleg nincs raktáron olcsóbb Kifli saját márkás alternatíva a kosarad tételeihez.",
        }

    # 4. LLM 2. villámhívás: válassza ki a valódi, raktáron lévő jelöltek közül a pontos párokat + darabszámot
    match_input = []
    items_by_id = {int(it["product_id"]): it for it in eligible_items}
    for old_pid, cands in candidates_by_old.items():
        old_it = items_by_id.get(old_pid)
        if not old_it:
            continue
        match_input.append(
            {
                "old": {
                    "product_id": old_pid,
                    "name": old_it["name"],
                    "quantity": old_it["quantity"],
                    "line_total_ft": old_it["line_total"],
                    "volume": f"{old_it['volume']} {old_it['unit']}",
                },
                "kifli_private_label_candidates": [
                    {
                        "product_id": int(p["productId"]),
                        "name": p["productName"],
                        "brand": p.get("brand", ""),
                        "price_ft": round(float(p.get("price") or 0)),
                        "amount": p.get("textualAmount", ""),
                    }
                    for p in cands
                ],
            }
        )

    pick_prompt = (
        "Válaszd ki minden kosár-tételhez a pontosan megfelelő, OLCSÓBB Kifli saját márkás helyettesítőt "
        "a megadott jelöltek közül! Csak akkor javasolj cserét, ha tényleg ugyanaz a terméktípus (pl. tej -> tej, "
        "tejföl -> tejföl, papírtörlő -> papírtörlő), a kiszerelést figyelembe véve add meg a helyes `new_quantity` "
        "darabszámot, és az új összár (`price_ft * new_quantity`) OLCSÓBB a jelenlegi `line_total_ft`-nél!\n"
        f"{allergen_note}\n"
        'Válaszolj SZIGORÚAN JSON tömbbel: [{"old_product_id": 123, "new_product_id": 456, "new_quantity": 2}]\n\n'
        f"Párosítandó tételek:\n{json.dumps(match_input, ensure_ascii=False)}"
    )
    pick_resp = await agent._chat_completion(
        client=client,
        messages=[
            {"role": "system", "content": "Csak érvényes JSON tömbbel válaszolj, magyarázat nélkül."},
            {"role": "user", "content": pick_prompt},
        ],
        temperature=0.1,
    )
    try:
        picks = _parse_json_from_llm(pick_resp.choices[0].message.content or "[]")
    except Exception as exc:
        log.warning("Private label pick JSON parse hiba: %s", exc)
        picks = []

    # 5. Szigorú szerver-oldali ár- és ID-validáció
    validated_swaps: list[dict[str, Any]] = []
    for p in picks:
        try:
            old_pid = int(p["old_product_id"])
            new_pid = int(p["new_product_id"])
            new_qty = max(1, int(p.get("new_quantity", 1)))
        except Exception:
            continue
        old_it = items_by_id.get(old_pid)
        new_prod = valid_new_products.get(new_pid)
        if not old_it or not new_prod or old_pid == new_pid:
            continue

        # Szigorú diéta-védelem: ha laktózmentes/gluténmentes kell, nem engedjük át a nem-mentes jelöltet!
        req_diet = detect_diet_requirements(old_it["name"], active_allergens)
        new_name_low = (new_prod.get("productName") or "").lower()
        if "laktózmentes" in req_diet and not any(
            w in new_name_low for w in ("laktózmentes", "laktozmentes", "növényi", "zab", "mandula", "kókusz")
        ):
            continue
        if "gluténmentes" in req_diet and not any(
            w in new_name_low for w in ("gluténmentes", "glutenmentes")
        ):
            continue

        new_unit_price = round(float(new_prod.get("price") or 0))
        new_line_total = new_unit_price * new_qty
        old_line_total = round(float(old_it["line_total"]))
        savings = old_line_total - new_line_total
        if savings < 20:
            continue

        validated_swaps.append(
            {
                "old_product_id": old_pid,
                "old_name": old_it["name"],
                "old_quantity": int(old_it["quantity"]),
                "old_price_ft": old_line_total,
                "old_image_url": old_it.get("image_url", ""),
                "new_product_id": new_pid,
                "new_name": new_prod.get("productName", ""),
                "new_brand": new_prod.get("brand", "Kifli"),
                "new_amount": new_prod.get("textualAmount", ""),
                "new_quantity": new_qty,
                "new_unit_price_ft": new_unit_price,
                "new_price_ft": new_line_total,
                "savings_ft": savings,
                "is_favorite": bool(new_prod.get("favourite", False)),
            }
        )

    auto_swaps, favorite_proposals = split_auto_vs_favorite_swaps(
        validated_swaps, fav_ids=fav_ids, fav_labels=fav_labels
    )

    # 6. NEM-kedvenc tételek AZONNALI tényleges cseréje a Kifli kosárban!
    applied_auto: list[dict[str, Any]] = []
    if auto_swaps:
        applied_auto = await execute_cart_swaps(kifli, auto_swaps)

    auto_savings_ft = sum(int(s["savings_ft"]) for s in applied_auto)
    return {
        "auto_swapped": applied_auto,
        "auto_savings_ft": auto_savings_ft,
        "favorite_proposals": favorite_proposals,
        "message": (
            f"{len(applied_auto)} terméket azonnal Kifli saját márkára cseréltem (-{auto_savings_ft} Ft)!"
            if applied_auto
            else (
                "Csak kedvelt márkáidhoz találtam olcsóbb Kifli alternatívát — dönts róluk a felugró ablakban!"
                if favorite_proposals
                else "A kosaradban jelenleg nem találtam olcsóbb Kifli saját márkás helyettesítőt."
            )
        ),
    }


async def execute_cart_swaps(
    kifli: KifliMCPManager, swaps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    0 AI-tokenes közvetlen csere a Kifli.hu kosárban:
    1) Hozzáadja az új Kifli saját márkás tételeket (`add_items_to_cart`)
    2) Eltávolítja a régi tételeket (`remove_cart_item`)
    """
    if not swaps:
        return []

    items_to_add = [
        {"productId": int(s["new_product_id"]), "quantity": max(1, int(s.get("new_quantity", 1)))}
        for s in swaps
    ]
    await kifli.call_tool_untruncated(
        "add_items_to_cart",
        {
            "items": items_to_add,
            "context": "Swap cart items to cheaper Kifli private-label products",
        },
    )

    succeeded: list[dict[str, Any]] = []
    for s in swaps:
        try:
            await kifli.call_tool_untruncated(
                "remove_cart_item",
                {
                    "product_id": int(s["old_product_id"]),
                    "context": "Remove original item after swapping to Kifli private label",
                },
            )
            succeeded.append(s)
        except Exception as exc:
            log.warning("Régi kosár tétel eltávolítása sikertelen (%s): %s", s["old_product_id"], exc)
    return succeeded
