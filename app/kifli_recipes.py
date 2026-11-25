from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.db import Database
from app.kifli_mcp import KifliMCPManager

log = logging.getLogger("kifli_otthon.kifli_recipes")

KIFLI_CDN = "https://cdn.kifli.hu/"

# Kurált Kifli.hu inspirációs receptek Demo módhoz / ha még nincs összekötve a Kifli fiók
DEMO_KIFLI_RECIPES: list[dict[str, Any]] = [
    {
        "kifli_recipe_id": 11792,
        "title": "Cézár wrap – Gyors és egészséges ebéd",
        "categories": ["ebed", "vacsora"],
        "servings": 4,
        "duration": "30 perc",
        "image_url": "https://cdn.kifli.hu/images/meals/large/recipe_11792_1777028593782_chicken-caesar-wrap-with-greek-yogurt-dressing_3668f1e9.jpg",
        "ingredients_preview": "Csirkemell filé, Római saláta, Búzatortilla, Paradicsom, Görög joghurt, Parmezán sajt, Dijoni mustár",
        "ingredients": [
            {"name": "csirkemell filé", "quantity": 400, "unit": "g"},
            {"name": "római saláta", "quantity": 1, "unit": "db"},
            {"name": "búzatortilla", "quantity": 4, "unit": "db"},
            {"name": "paradicsom", "quantity": 2, "unit": "db"},
            {"name": "görög joghurt", "quantity": 150, "unit": "g"},
            {"name": "parmezán sajt", "quantity": 50, "unit": "g"},
        ],
        "instructions": "Süsd aranybarnára a fűszerezett csirkemellcsíkokat, keverd ki a joghurtos-parmezános öntetet, majd tekerd tortillába a friss zöldségekkel.",
        "healthy_score": 5,
        "kcal_per_serving": 430,
        "protein_g": 36.0,
        "carbs_g": 38.0,
        "fat_g": 14.0,
    },
    {
        "kifli_recipe_id": 10006,
        "title": "Csirkés-zöldséges bulgur egytál",
        "categories": ["ebed"],
        "servings": 4,
        "duration": "35 perc",
        "image_url": "https://cdn.kifli.hu/images/meals/large/recipe_10006_1787926958213_chicken-and-vegetable-bulgur-bowl_e633204d.jpg",
        "ingredients_preview": "Csirkemell filé, Bulgur, Barna csiperkegomba, Brokkoli, Vöröshagyma, Friss petrezselyem",
        "ingredients": [
            {"name": "csirkemell filé", "quantity": 500, "unit": "g"},
            {"name": "bulgur", "quantity": 250, "unit": "g"},
            {"name": "barna csiperkegomba", "quantity": 250, "unit": "g"},
            {"name": "brokkoli", "quantity": 1, "unit": "db"},
            {"name": "vöröshagyma", "quantity": 1, "unit": "db"},
        ],
        "instructions": "Pirítsd meg a hagymát, gombát és csirkemellet, főzd hozzá a bulgurt és párolt brokkolit, majd friss petrezselyemmel tálald.",
        "healthy_score": 5,
        "kcal_per_serving": 470,
        "protein_g": 41.0,
        "carbs_g": 48.0,
        "fat_g": 11.0,
    },
    {
        "kifli_recipe_id": 12959,
        "title": "Parmezános ropogós csirkemell",
        "categories": ["ebed"],
        "servings": 4,
        "duration": "40 perc",
        "image_url": "https://cdn.kifli.hu/images/meals/large/recipe_12959_1777237421485_parmesan-crusted-chicken-schnitzel_3619b6df.jpg",
        "ingredients_preview": "Csirkemell filé, Parmezán sajt, Tojás, Tej, Búzafinomliszt, Zsemlemorzsa",
        "ingredients": [
            {"name": "csirkemell filé", "quantity": 600, "unit": "g"},
            {"name": "parmezán sajt", "quantity": 80, "unit": "g"},
            {"name": "tojás", "quantity": 2, "unit": "db"},
            {"name": "zsemlemorzsa", "quantity": 120, "unit": "g"},
        ],
        "instructions": "Forgasd a csirkemellszeleteket lisztbe, tojásba, majd parmezánnal elkevert zsemlemorzsába, és süsd ropogósra.",
        "healthy_score": 3,
        "kcal_per_serving": 540,
        "protein_g": 45.0,
        "carbs_g": 28.0,
        "fat_g": 26.0,
    },
]

_QTY_UNIT_RE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(kg|dkg|g|ml|dl|cl|l|db|ek|tk|evőkanál|teáskanál|csipet|csomag|csokor|gerezd|fej|szelet|doboz|üveg|pohár)\b\.?\s+(.+)$",
    re.IGNORECASE,
)


def parse_hungarian_ingredient_line(line: str) -> dict[str, Any]:
    raw = " ".join((line or "").strip().split())
    if not raw:
        return {"name": "", "quantity": 1.0, "unit": "db"}
    m = _QTY_UNIT_RE.match(raw)
    if m:
        qty = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        unit_map = {"evőkanál": "ek", "teáskanál": "tk"}
        unit = unit_map.get(unit, unit)
        name = m.group(3).strip(" ,.-")
        return {"name": name or raw, "quantity": qty, "unit": unit}
    return {"name": raw, "quantity": 1.0, "unit": "db"}


def _normalize_kifli_image(img: str | None) -> str:
    val = (img or "").strip()
    if not val:
        return ""
    if val.startswith(("http://", "https://")):
        return val
    return KIFLI_CDN + val.lstrip("/")


def _parse_servings(val: Any) -> int:
    m = re.search(r"(\d+)", str(val or ""))
    return max(1, int(m.group(1))) if m else 2


def _guess_categories(title: str, query: str = "") -> list[str]:
    text = f"{title} {query}".lower()
    cats: list[str] = []
    if any(w in text for w in ("reggeli", "zabkása", "omlett", "rántotta", "palacsinta", "turmix", "granola")):
        cats.append("reggeli")
    if any(w in text for w in ("vacsora", "saláta", "wrap", "szendvics", "pirítós", "bruschetta")):
        cats.append("vacsora")
    if not cats or any(w in text for w in ("ebéd", "leves", "tészta", "csirke", "egytál", "főzelék", "pörkölt", "curry", "rizottó")):
        if "ebed" not in cats:
            cats.append("ebed")
    return cats or ["ebed"]


async def search_kifli_recipes(
    kifli: KifliMCPManager | None,
    query: str = "",
    limit: int = 9,
    is_demo: bool = False,
) -> dict[str, Any]:
    clean_q = (query or "").strip() or "gyors egészséges ebéd"
    st = await kifli.get_status() if (kifli and not is_demo) else {"authenticated": False}

    if not st.get("authenticated") or kifli is None or is_demo:
        q_low = (query or "").strip().lower()
        filtered = [
            r
            for r in DEMO_KIFLI_RECIPES
            if not q_low
            or q_low in r["title"].lower()
            or q_low in r["ingredients_preview"].lower()
        ]
        return {
            "is_live_kifli": False,
            "query": clean_q,
            "recipes": filtered or DEMO_KIFLI_RECIPES,
        }

    try:
        raw = await kifli.call_tool_untruncated(
            "search_recipes_by_vector_similarity",
            {
                "query": clean_q,
                "limit": max(1, min(12, int(limit))),
                "context": "Browse Kifli.hu recipes in recipe discovery tab",
            },
        )
        payload = json.loads(raw)
        items = payload.get("data") or []
        out: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            rid = it.get("id") or it.get("recipe_id")
            if rid is None:
                continue
            title = str(it.get("name") or "").strip()
            ing_preview = str(it.get("ingredients") or "").strip()
            out.append(
                {
                    "kifli_recipe_id": int(rid),
                    "title": title,
                    "categories": _guess_categories(title, clean_q),
                    "servings": _parse_servings(it.get("servings")),
                    "duration": str(it.get("duration") or ""),
                    "image_url": _normalize_kifli_image(it.get("image_url")),
                    "ingredients_preview": ing_preview,
                    "healthy_score": 4 if "egészséges" in title.lower() or "saláta" in title.lower() else 3,
                    "kcal_per_serving": 0,
                    "protein_g": 0.0,
                    "carbs_g": 0.0,
                    "fat_g": 0.0,
                }
            )
        return {"is_live_kifli": True, "query": clean_q, "recipes": out}
    except Exception as exc:
        log.warning("Kifli recept keresés hiba (fallback minta receptekre): %s", exc)
        return {
            "is_live_kifli": False,
            "query": clean_q,
            "recipes": DEMO_KIFLI_RECIPES,
            "warning": str(exc),
        }


async def import_kifli_recipe_to_db(
    db: Database,
    kifli: KifliMCPManager | None,
    kifli_recipe_id: int,
    user_id: int,
    is_demo: bool = False,
    fallback_title: str = "",
    fallback_image_url: str = "",
    fallback_ingredients_preview: str = "",
) -> dict[str, Any]:
    # Demo / kurált minta recept közvetlen mentése
    demo_match = next(
        (r for r in DEMO_KIFLI_RECIPES if int(r["kifli_recipe_id"]) == int(kifli_recipe_id)),
        None,
    )
    st = await kifli.get_status() if (kifli and not is_demo) else {"authenticated": False}

    if (is_demo or not st.get("authenticated") or kifli is None) and demo_match:
        return db.create_or_update_recipe(
            title=demo_match["title"],
            categories=demo_match["categories"],
            servings=demo_match["servings"],
            instructions=demo_match["instructions"],
            image_url=demo_match["image_url"],
            healthy_score=demo_match["healthy_score"],
            kcal_per_serving=demo_match["kcal_per_serving"],
            protein_g=demo_match["protein_g"],
            carbs_g=demo_match["carbs_g"],
            fat_g=demo_match["fat_g"],
            is_public=False,
            ingredients=demo_match["ingredients"],
            user_id=user_id,
        )

    if kifli is not None and st.get("authenticated") and not is_demo:
        raw = await kifli.call_tool_untruncated(
            "get_recipe_detail",
            {
                "recipe_id": int(kifli_recipe_id),
                "include_meta": ["image", "author", "link"],
                "context": "Import selected Kifli.hu recipe into user's recipe book",
            },
        )
        detail = json.loads(raw)
        title = str(detail.get("name") or fallback_title or f"Kifli recept #{kifli_recipe_id}").strip()
        steps = detail.get("steps") or []
        instructions = "\n".join(
            f"{idx + 1}. {s.get('text', '').strip()}"
            for idx, s in enumerate(steps)
            if isinstance(s, dict) and s.get("text")
        )
        raw_ings = detail.get("ingredients") or []
        parsed_ings = [
            parse_hungarian_ingredient_line(str(ing.get("ingredient_name") or ""))
            for ing in raw_ings
            if isinstance(ing, dict) and ing.get("ingredient_name")
        ]
        parsed_ings = [i for i in parsed_ings if i["name"]]
        img = _normalize_kifli_image(detail.get("image") or detail.get("image_url") or fallback_image_url)
        link = str(detail.get("link") or "").strip()
        servings = _parse_servings(detail.get("servings"))

        return db.create_or_update_recipe(
            title=title,
            categories=_guess_categories(title),
            servings=servings,
            instructions=instructions,
            source_url=link,
            image_url=img,
            healthy_score=4 if "egészséges" in title.lower() or "saláta" in title.lower() else 3,
            is_public=False,
            ingredients=parsed_ings or [{"name": "hozzávalók", "quantity": 1, "unit": "db"}],
            user_id=user_id,
        )

    # Ha csak előnézetből mentjük
    parsed_fallback = [
        parse_hungarian_ingredient_line(p)
        for p in (fallback_ingredients_preview or "").split(",")
        if p.strip()
    ]
    return db.create_or_update_recipe(
        title=fallback_title or f"Kifli recept #{kifli_recipe_id}",
        categories=_guess_categories(fallback_title),
        servings=2,
        image_url=fallback_image_url,
        is_public=False,
        ingredients=parsed_fallback or [{"name": "hozzávalók", "quantity": 1, "unit": "db"}],
        user_id=user_id,
    )
