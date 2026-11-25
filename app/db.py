from __future__ import annotations

import datetime as dt
import json
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DAYS_HU = [
    ("hetfo", "Hétfő"),
    ("kedd", "Kedd"),
    ("szerda", "Szerda"),
    ("csutortok", "Csütörtök"),
    ("pentek", "Péntek"),
    ("szombat", "Szombat"),
    ("vasarnap", "Vasárnap"),
]

MEAL_TYPES = ("reggeli", "ebed", "vacsora")

DEFAULT_STAPLES = [
    "só",
    "fekete bors",
    "étolaj",
    "olívaolaj",
    "finomliszt",
    "kristálycukor",
    "pirospaprika",
    "babérlevél",
    "fokhagyma",
    "ecet",
]


def normalize_key(text: str) -> str:
    """Kisbetűs, szóköz-normalizált kulcs hozzávaló összevonáshoz és kedvenc márkákhoz."""
    cleaned = " ".join(text.strip().lower().split())
    return cleaned


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def current_week_monday(today: dt.date | None = None) -> str:
    d = today or dt.date.today()
    monday = d - dt.timedelta(days=d.weekday())
    return monday.isoformat()


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS recipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    servings INTEGER NOT NULL DEFAULT 2,
                    instructions TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    healthy_score INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS recipe_ingredients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1,
                    unit TEXT NOT NULL DEFAULT 'db',
                    is_staple INTEGER NOT NULL DEFAULT 0,
                    brand_hint TEXT NOT NULL DEFAULT ''
                );

                -- Általános / Háztartási egyszeri lista 3-lépcsős anti-loop állapotgéppel:
                -- PENDING -> IN_CART -> ORDERED
                CREATE TABLE IF NOT EXISTS general_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1,
                    unit TEXT NOT NULL DEFAULT 'db',
                    brand_hint TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_CART', 'ORDERED')),
                    kifli_product_id TEXT NOT NULL DEFAULT '',
                    kifli_product_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    carted_at TEXT,
                    ordered_at TEXT
                );

                CREATE TABLE IF NOT EXISTS staples (
                    key TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_preferences (
                    ingredient_key TEXT PRIMARY KEY,
                    ingredient_label TEXT NOT NULL,
                    kifli_product_id TEXT NOT NULL,
                    kifli_product_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS weekly_plans (
                    week_start TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'IN_CART', 'ORDERED')),
                    plan_json TEXT NOT NULL,
                    adhoc_items_json TEXT NOT NULL DEFAULT '[]',
                    recommendation_note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    source TEXT NOT NULL DEFAULT 'web',
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS processed_kifli_orders (
                    order_id TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS planner_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Páros Kaja Tinder Match szobák (2 telefon közös húzogatása -> IT'S A MATCH!)
                CREATE TABLE IF NOT EXISTS tinder_sessions (
                    code TEXT PRIMARY KEY,
                    meal_type TEXT NOT NULL DEFAULT 'ebed',
                    target_days_json TEXT NOT NULL DEFAULT '["hetfo","kedd"]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS tinder_swipes (
                    session_code TEXT NOT NULL REFERENCES tinder_sessions(code) ON DELETE CASCADE,
                    user_slot TEXT NOT NULL CHECK (user_slot IN ('p1', 'p2')),
                    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    decision TEXT NOT NULL CHECK (decision IN ('like', 'pass')),
                    swiped_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (session_code, user_slot, recipe_id)
                );
                """
            )

            # Zökkenőmentes séma-migráció meglévő SQLite DB-hez (NAS adatmegőrzés)
            recipe_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(recipes)").fetchall()
            }
            if "image_url" not in recipe_cols:
                conn.execute("ALTER TABLE recipes ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
            if "healthy_score" not in recipe_cols:
                conn.execute("ALTER TABLE recipes ADD COLUMN healthy_score INTEGER NOT NULL DEFAULT 3")

            existing_staples = conn.execute("SELECT COUNT(*) AS c FROM staples").fetchone()["c"]
            if existing_staples == 0:
                for item in DEFAULT_STAPLES:
                    conn.execute(
                        "INSERT OR IGNORE INTO staples (key, display_name) VALUES (?, ?)",
                        (normalize_key(item), item),
                    )

            existing_recipes = conn.execute("SELECT COUNT(*) AS c FROM recipes").fetchone()["c"]
            if existing_recipes == 0:
                self._seed_starter_recipes(conn)

    def _seed_starter_recipes(self, conn: sqlite3.Connection) -> None:
        starters = [
            {
                "title": "Zabkása banánnal és áfonyával",
                "categories": ["reggeli"],
                "servings": 2,
                "instructions": "A zabpelyhet tejjel felfőzzük, tetejére karikázott banán és friss áfonya kerül.",
                "ingredients": [
                    {"name": "zabpehely", "quantity": 120, "unit": "g", "is_staple": False},
                    {"name": "tej 2,8%", "quantity": 0.4, "unit": "l", "is_staple": False},
                    {"name": "banán", "quantity": 2, "unit": "db", "is_staple": False},
                    {"name": "áfonya", "quantity": 125, "unit": "g", "is_staple": False},
                ],
            },
            {
                "title": "Sonkás-sajtos rántotta kovászos kenyérrel",
                "categories": ["reggeli", "vacsora"],
                "servings": 2,
                "instructions": "4-5 tojásból lágy rántotta, pirított kovászos kenyérrel.",
                "ingredients": [
                    {"name": "tojás", "quantity": 5, "unit": "db", "is_staple": False},
                    {"name": "gépsonka", "quantity": 100, "unit": "g", "is_staple": False},
                    {"name": "trappista vagy gouda sajt", "quantity": 80, "unit": "g", "is_staple": False},
                    {"name": "kovászos kenyér", "quantity": 0.5, "unit": "db", "is_staple": False},
                    {"name": "só", "quantity": 1, "unit": "csipet", "is_staple": True},
                ],
            },
            {
                "title": "Csirkepaprikás nokedlivel",
                "categories": ["ebed"],
                "servings": 4,
                "instructions": "Klasszikus tejfölös csirkepaprikás házi vagy kész nokedlivel.",
                "ingredients": [
                    {"name": "csirkemell vagy csirkecomb filé", "quantity": 800, "unit": "g", "is_staple": False},
                    {"name": "vöröshagyma", "quantity": 2, "unit": "db", "is_staple": False},
                    {"name": "tejföl 20%", "quantity": 330, "unit": "g", "is_staple": False},
                    {"name": "friss nokedli", "quantity": 500, "unit": "g", "is_staple": False},
                    {"name": "pirospaprika", "quantity": 2, "unit": "ek", "is_staple": True},
                    {"name": "étolaj", "quantity": 2, "unit": "ek", "is_staple": True},
                ],
            },
            {
                "title": "Bolognai spagetti parmezánnal",
                "categories": ["ebed", "vacsora"],
                "servings": 4,
                "instructions": "Darált marhahúsos paradicsomos ragu spagettivel és reszelt parmezánnal.",
                "ingredients": [
                    {"name": "darált marhahús", "quantity": 500, "unit": "g", "is_staple": False},
                    {"name": "spagetti tészta", "quantity": 500, "unit": "g", "is_staple": False},
                    {"name": "passzírozott paradicsom", "quantity": 500, "unit": "g", "is_staple": False},
                    {"name": "parmezán sajt", "quantity": 100, "unit": "g", "is_staple": False},
                    {"name": "vöröshagyma", "quantity": 1, "unit": "db", "is_staple": False},
                ],
            },
            {
                "title": "Cézár saláta grillezett csirkével",
                "categories": ["vacsora", "ebed"],
                "servings": 2,
                "instructions": "Ropogós római saláta pirított csirkemellcsíkokkal és parmezánnal.",
                "ingredients": [
                    {"name": "római saláta", "quantity": 1, "unit": "db", "is_staple": False},
                    {"name": "csirkemell filé", "quantity": 400, "unit": "g", "is_staple": False},
                    {"name": "cézár öntet", "quantity": 1, "unit": "üveg", "is_staple": False},
                    {"name": "parmezán sajt", "quantity": 50, "unit": "g", "is_staple": False},
                ],
            },
        ]
        for r in starters:
            cur = conn.execute(
                """
                INSERT INTO recipes (title, categories_json, servings, instructions)
                VALUES (?, ?, ?, ?)
                """,
                (r["title"], json.dumps(r["categories"], ensure_ascii=False), r["servings"], r["instructions"]),
            )
            recipe_id = cur.lastrowid
            for ing in r["ingredients"]:
                conn.execute(
                    """
                    INSERT INTO recipe_ingredients (recipe_id, name, quantity, unit, is_staple, brand_hint)
                    VALUES (?, ?, ?, ?, ?, '')
                    """,
                    (recipe_id, ing["name"], ing["quantity"], ing["unit"], 1 if ing["is_staple"] else 0),
                )

    # -------------------------------------------------------------------------
    # Receptek
    # -------------------------------------------------------------------------
    def list_recipes(self, category: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM recipes ORDER BY title COLLATE NOCASE").fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                cats = json.loads(row["categories_json"])
                if category and category not in cats:
                    continue
                ings = conn.execute(
                    "SELECT id, name, quantity, unit, is_staple, brand_hint FROM recipe_ingredients WHERE recipe_id = ? ORDER BY id",
                    (row["id"],),
                ).fetchall()
                result.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "categories": cats,
                        "servings": row["servings"],
                        "instructions": row["instructions"],
                        "source_url": row["source_url"],
                        "image_url": row["image_url"] or "",
                        "healthy_score": max(1, min(5, int(row["healthy_score"] or 3))),
                        "ingredients": [
                            {
                                "id": i["id"],
                                "name": i["name"],
                                "quantity": i["quantity"],
                                "unit": i["unit"],
                                "is_staple": bool(i["is_staple"]),
                                "brand_hint": i["brand_hint"],
                            }
                            for i in ings
                        ],
                    }
                )
            return result

    def create_or_update_recipe(
        self,
        title: str,
        categories: list[str],
        ingredients: list[dict[str, Any]],
        servings: int = 2,
        instructions: str = "",
        source_url: str = "",
        recipe_id: int | None = None,
        image_url: str | None = None,
        healthy_score: int = 3,
    ) -> dict[str, Any]:
        valid_cats = [c for c in categories if c in MEAL_TYPES] or ["ebed"]
        clamped_score = max(1, min(5, int(healthy_score or 3)))
        staples_set = {s["key"] for s in self.list_staples()}
        with self.connect() as conn:
            if recipe_id is not None:
                if image_url is None:
                    prev = conn.execute(
                        "SELECT image_url FROM recipes WHERE id = ?", (recipe_id,)
                    ).fetchone()
                    final_image_url = prev["image_url"] if prev else ""
                else:
                    final_image_url = image_url.strip()

                conn.execute(
                    """
                    UPDATE recipes
                    SET title = ?, categories_json = ?, servings = ?, instructions = ?, source_url = ?, image_url = ?, healthy_score = ?
                    WHERE id = ?
                    """,
                    (
                        title.strip(),
                        json.dumps(valid_cats, ensure_ascii=False),
                        max(1, int(servings)),
                        instructions.strip(),
                        source_url.strip(),
                        final_image_url,
                        clamped_score,
                        recipe_id,
                    ),
                )
                conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
                rid = recipe_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO recipes (title, categories_json, servings, instructions, source_url, image_url, healthy_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title.strip(),
                        json.dumps(valid_cats, ensure_ascii=False),
                        max(1, int(servings)),
                        instructions.strip(),
                        source_url.strip(),
                        (image_url or "").strip(),
                        clamped_score,
                    ),
                )
                rid = int(cur.lastrowid)

            for ing in ingredients:
                name = str(ing.get("name", "")).strip()
                if not name:
                    continue
                is_staple = bool(ing.get("is_staple", False)) or (normalize_key(name) in staples_set)
                conn.execute(
                    """
                    INSERT INTO recipe_ingredients (recipe_id, name, quantity, unit, is_staple, brand_hint)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rid,
                        name,
                        float(ing.get("quantity", 1) or 1),
                        str(ing.get("unit", "db") or "db").strip(),
                        1 if is_staple else 0,
                        str(ing.get("brand_hint", "") or "").strip(),
                    ),
                )
        matches = [r for r in self.list_recipes() if r["id"] == rid]
        return matches[0]

    def set_recipe_image(self, recipe_id: int, image_url: str) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE recipes SET image_url = ? WHERE id = ?",
                (image_url.strip(), int(recipe_id)),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
        return [r for r in self.list_recipes() if r["id"] == int(recipe_id)][0]

    def set_recipe_healthy_score(self, recipe_id: int, healthy_score: int) -> dict[str, Any]:
        clamped = max(1, min(5, int(healthy_score)))
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE recipes SET healthy_score = ? WHERE id = ?",
                (clamped, int(recipe_id)),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
        return [r for r in self.list_recipes() if r["id"] == int(recipe_id)][0]

    def delete_recipe(self, recipe_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Általános / Háztartási egyszeri lista (Anti-loop állapotgéppel!)
    # -------------------------------------------------------------------------
    def list_general_items(self, include_ordered: bool = False) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if include_ordered:
                rows = conn.execute(
                    "SELECT * FROM general_items ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM general_items WHERE status IN ('PENDING', 'IN_CART') ORDER BY status DESC, id ASC"
                ).fetchall()
            return [dict(r) for r in rows]

    def add_general_item(
        self,
        name: str,
        quantity: float = 1.0,
        unit: str = "db",
        brand_hint: str = "",
    ) -> dict[str, Any]:
        clean_name = name.strip()
        clean_unit = (unit or "db").strip()
        clean_brand = (brand_hint or "").strip()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM general_items
                WHERE status = 'PENDING'
                  AND lower(trim(name)) = lower(?)
                  AND lower(trim(unit)) = lower(?)
                  AND lower(trim(brand_hint)) = lower(?)
                """,
                (clean_name, clean_unit, clean_brand),
            ).fetchone()
            if existing:
                new_qty = float(existing["quantity"]) + float(quantity)
                conn.execute(
                    "UPDATE general_items SET quantity = ? WHERE id = ?",
                    (new_qty, existing["id"]),
                )
                item_id = int(existing["id"])
            else:
                cur = conn.execute(
                    """
                    INSERT INTO general_items (name, quantity, unit, brand_hint, status)
                    VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                    (clean_name, float(quantity), clean_unit, clean_brand),
                )
                item_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM general_items WHERE id = ?", (item_id,)).fetchone()
            return dict(row)

    def mark_general_items_in_cart(
        self, carted_items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Csak azokat a PENDING elemeket állítja IN_CART státuszra, amiket az AI ténylegesen
        be tudott tenni a Kifli kosárba. Ami készlethiányos volt, marad PENDING!
        """
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        updated: list[dict[str, Any]] = []
        with self.connect() as conn:
            for entry in carted_items:
                item_id = int(entry["id"])
                pid = str(entry.get("kifli_product_id", "") or "").strip()
                pname = str(entry.get("kifli_product_name", "") or "").strip()
                conn.execute(
                    """
                    UPDATE general_items
                    SET status = 'IN_CART',
                        kifli_product_id = ?,
                        kifli_product_name = ?,
                        carted_at = ?
                    WHERE id = ? AND status = 'PENDING'
                    """,
                    (pid, pname, now_iso, item_id),
                )
                row = conn.execute("SELECT * FROM general_items WHERE id = ?", (item_id,)).fetchone()
                if row:
                    updated.append(dict(row))
        return updated

    def finalize_order_and_clear_general_items(
        self, kifli_order_id: str | None = None, include_pending_if_forced: bool = False
    ) -> dict[str, Any]:
        """
        Amikor kiment a Kifli rendelés, végleg ORDERED-re zárja (eltünteti az aktív listáról)
        az IN_CART elemeket + lezárja az aktuális heti tervet, így SOHA nem loopol a következő héten!
        """
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        with self.connect() as conn:
            if kifli_order_id:
                already = conn.execute(
                    "SELECT 1 FROM processed_kifli_orders WHERE order_id = ?",
                    (str(kifli_order_id),),
                ).fetchone()
                if already:
                    return {"cleared_count": 0, "already_processed": True}
                conn.execute(
                    "INSERT INTO processed_kifli_orders (order_id, processed_at) VALUES (?, ?)",
                    (str(kifli_order_id), now_iso),
                )

            target_statuses = ("IN_CART", "PENDING") if include_pending_if_forced else ("IN_CART",)
            placeholders = ",".join("?" for _ in target_statuses)
            rows = conn.execute(
                f"SELECT id, name, brand_hint FROM general_items WHERE status IN ({placeholders})",
                target_statuses,
            ).fetchall()
            cleared_items = [dict(r) for r in rows]

            conn.execute(
                f"""
                UPDATE general_items
                SET status = 'ORDERED', ordered_at = ?
                WHERE status IN ({placeholders})
                """,
                (now_iso, *target_statuses),
            )

            week_key = current_week_monday()
            conn.execute(
                """
                UPDATE weekly_plans
                SET status = 'ORDERED', adhoc_items_json = '[]', updated_at = ?
                WHERE week_start = ?
                """,
                (now_iso, week_key),
            )
            return {
                "cleared_count": len(cleared_items),
                "cleared_items": cleared_items,
                "already_processed": False,
            }

    def revert_in_cart_general_items_to_pending(self) -> int:
        """Ha mégsem ment ki a rendelés és kiürült a kosár, 1 klikkel visszatehető PENDING-re."""
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE general_items
                SET status = 'PENDING', carted_at = NULL
                WHERE status = 'IN_CART'
                """
            )
            return cur.rowcount

    def delete_general_item(self, item_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM general_items WHERE id = ?", (item_id,))
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Kamra-alapanyagok & Kedvenc Kifli márkák memóriája
    # -------------------------------------------------------------------------
    def list_staples(self) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, display_name FROM staples ORDER BY display_name").fetchall()
            return [dict(r) for r in rows]

    def add_staple(self, name: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO staples (key, display_name) VALUES (?, ?)",
                (normalize_key(name), name.strip()),
            )

    def delete_staple(self, key: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM staples WHERE key = ?", (normalize_key(key),))
            return cur.rowcount > 0

    def list_product_preferences(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM product_preferences ORDER BY ingredient_label COLLATE NOCASE"
            ).fetchall()
            return [dict(r) for r in rows]

    def save_product_preference(
        self, ingredient_name: str, kifli_product_id: str, kifli_product_name: str
    ) -> dict[str, Any]:
        key = normalize_key(ingredient_name)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO product_preferences (ingredient_key, ingredient_label, kifli_product_id, kifli_product_name, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(ingredient_key) DO UPDATE SET
                    ingredient_label = excluded.ingredient_label,
                    kifli_product_id = excluded.kifli_product_id,
                    kifli_product_name = excluded.kifli_product_name,
                    updated_at = datetime('now')
                """,
                (key, ingredient_name.strip(), str(kifli_product_id).strip(), kifli_product_name.strip()),
            )
            row = conn.execute(
                "SELECT * FROM product_preferences WHERE ingredient_key = ?", (key,)
            ).fetchone()
            return dict(row)

    def delete_product_preference(self, ingredient_key: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM product_preferences WHERE ingredient_key = ?",
                (normalize_key(ingredient_key),),
            )
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Heti Menüterv & Összesített Bevásárlólista
    # -------------------------------------------------------------------------
    def get_weekly_plan(self, week_start: str | None = None) -> dict[str, Any] | None:
        wk = week_start or current_week_monday()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM weekly_plans WHERE week_start = ?", (wk,)).fetchone()
            if not row:
                return None
            return {
                "week_start": row["week_start"],
                "status": row["status"],
                "days": json.loads(row["plan_json"]),
                "adhoc_items": json.loads(row["adhoc_items_json"]),
                "recommendation_note": row["recommendation_note"],
                "updated_at": row["updated_at"],
            }

    def save_weekly_plan(
        self,
        days: dict[str, Any],
        week_start: str | None = None,
        status: str = "DRAFT",
        adhoc_items: list[dict[str, Any]] | None = None,
        recommendation_note: str = "",
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        existing = self.get_weekly_plan(wk)
        final_adhoc = (
            adhoc_items
            if adhoc_items is not None
            else (existing["adhoc_items"] if existing else [])
        )
        final_note = recommendation_note or (existing["recommendation_note"] if existing else "")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans (week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(week_start) DO UPDATE SET
                    status = excluded.status,
                    plan_json = excluded.plan_json,
                    adhoc_items_json = excluded.adhoc_items_json,
                    recommendation_note = excluded.recommendation_note,
                    updated_at = datetime('now')
                """,
                (
                    wk,
                    status,
                    json.dumps(days, ensure_ascii=False),
                    json.dumps(final_adhoc, ensure_ascii=False),
                    final_note,
                ),
            )
        return self.get_weekly_plan(wk) or {}

    def update_weekly_meal_slot(
        self,
        day_key: str,
        meal_type: str,
        title: str,
        recipe_id: int | None = None,
        is_recommendation: bool = False,
        custom_ingredients: list[dict[str, Any]] | None = None,
        week_start: str | None = None,
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk)
        days = plan["days"] if plan else {d[0]: {} for d in DAYS_HU}
        day_norm = strip_accents(day_key.lower().strip())
        valid_day_keys = {d[0] for d in DAYS_HU}
        if day_norm not in valid_day_keys:
            raise ValueError(f"Ismeretlen nap: {day_key}. Választható: {', '.join(valid_day_keys)}")
        meal_norm = strip_accents(meal_type.lower().strip())
        if meal_norm not in MEAL_TYPES:
            raise ValueError(f"Ismeretlen étkezés: {meal_type}. Választható: reggeli, ebed, vacsora")

        days.setdefault(day_norm, {})[meal_norm] = {
            "title": title.strip(),
            "recipe_id": recipe_id,
            "is_recommendation": bool(is_recommendation),
            "custom_ingredients": custom_ingredients or [],
        }
        return self.save_weekly_plan(days=days, week_start=wk)

    def set_weekly_meal_slots_manual(
        self,
        day_keys: list[str],
        meal_type: str,
        recipe_id: int | None = None,
        custom_title: str = "",
        clear: bool = False,
        week_start: str | None = None,
    ) -> dict[str, Any]:
        """0 AI-tokenes közvetlen étkezés-csere saját receptből (akár egyszerre több napra is)."""
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk)
        days = plan["days"] if plan else {d[0]: {} for d in DAYS_HU}
        valid_day_keys = {d[0] for d in DAYS_HU}
        meal_norm = strip_accents(meal_type.lower().strip())
        if meal_norm not in MEAL_TYPES:
            raise ValueError(f"Ismeretlen étkezés: {meal_type}")

        resolved_title = custom_title.strip()
        if recipe_id is not None:
            matches = [r for r in self.list_recipes() if r["id"] == int(recipe_id)]
            if not matches:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
            resolved_title = matches[0]["title"]

        for dk in day_keys:
            day_norm = strip_accents(dk.lower().strip())
            if day_norm not in valid_day_keys:
                continue
            day_dict = days.setdefault(day_norm, {})
            if clear:
                day_dict.pop(meal_norm, None)
            else:
                if not resolved_title:
                    raise ValueError("Adj meg egy receptet vagy ételnevet!")
                day_dict[meal_norm] = {
                    "title": resolved_title,
                    "recipe_id": int(recipe_id) if recipe_id is not None else None,
                    "is_recommendation": False,
                    "custom_ingredients": [],
                }
        return self.save_weekly_plan(days=days, week_start=wk)

    def reset_weekly_plan(self, week_start: str | None = None) -> dict[str, Any]:
        """0 AI-tokenes teljes heti menü nullázás üresre."""
        wk = week_start or current_week_monday()
        empty_days = {d[0]: {} for d in DAYS_HU}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans (week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at)
                VALUES (?, 'DRAFT', ?, '[]', '', datetime('now'))
                ON CONFLICT(week_start) DO UPDATE SET
                    status = 'DRAFT',
                    plan_json = excluded.plan_json,
                    adhoc_items_json = '[]',
                    recommendation_note = '',
                    updated_at = datetime('now')
                """,
                (wk, json.dumps(empty_days, ensure_ascii=False)),
            )
        return self.get_weekly_plan(wk) or {}

    def add_adhoc_item_to_week(
        self,
        name: str,
        quantity: float = 1.0,
        unit: str = "db",
        brand_hint: str = "",
        week_start: str | None = None,
    ) -> dict[str, Any]:
        """Menet közben chatben kért plusz tétel (pl. 'adj hozzá még 2 tejet mert most jutott eszembe')."""
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk)
        days = plan["days"] if plan else {d[0]: {} for d in DAYS_HU}
        adhoc = list(plan["adhoc_items"]) if plan else []
        adhoc.append(
            {
                "name": name.strip(),
                "quantity": float(quantity),
                "unit": (unit or "db").strip(),
                "brand_hint": (brand_hint or "").strip(),
            }
        )
        return self.save_weekly_plan(days=days, week_start=wk, adhoc_items=adhoc)

    def aggregate_shopping_list(self, week_start: str | None = None) -> dict[str, Any]:
        """
        Összevonja a heti menü összes hozzávalóját + az adhoc tételeket + az Általános PENDING listát,
        különválasztja a kamra-alapanyagokat, és hozzárendeli a kedvenc Kifli termékeket.
        """
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk)
        recipes_by_id = {r["id"]: r for r in self.list_recipes()}
        staples_keys = {s["key"] for s in self.list_staples()}
        prefs_by_key = {p["ingredient_key"]: p for p in self.list_product_preferences()}

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        staples_needed: set[str] = set()

        def _accumulate(
            name: str,
            qty: float,
            unit: str,
            is_staple: bool = False,
            brand_hint: str = "",
            origin: str = "",
        ) -> None:
            nkey = normalize_key(name)
            ukey = normalize_key(unit or "db")
            if is_staple or nkey in staples_keys:
                staples_needed.add(name.strip())
                return
            bucket_key = (nkey, ukey)
            if bucket_key not in merged:
                pref = prefs_by_key.get(nkey)
                merged[bucket_key] = {
                    "name": name.strip(),
                    "quantity": float(qty),
                    "unit": unit.strip() or "db",
                    "brand_hint": brand_hint.strip(),
                    "preferred_kifli_product": (
                        {
                            "id": pref["kifli_product_id"],
                            "name": pref["kifli_product_name"],
                        }
                        if pref
                        else None
                    ),
                    "used_in": [origin] if origin else [],
                }
            else:
                merged[bucket_key]["quantity"] = round(merged[bucket_key]["quantity"] + float(qty), 2)
                if brand_hint and not merged[bucket_key]["brand_hint"]:
                    merged[bucket_key]["brand_hint"] = brand_hint.strip()
                if origin and origin not in merged[bucket_key]["used_in"]:
                    merged[bucket_key]["used_in"].append(origin)

        if plan:
            for day_code, day_label in DAYS_HU:
                day_slots = plan["days"].get(day_code, {})
                for meal_code in MEAL_TYPES:
                    slot = day_slots.get(meal_code)
                    if not slot:
                        continue
                    origin_label = f"{day_label} {meal_code}: {slot.get('title', '')}"
                    rid = slot.get("recipe_id")
                    custom_ings = slot.get("custom_ingredients") or []
                    if rid and rid in recipes_by_id and not custom_ings:
                        for ing in recipes_by_id[rid]["ingredients"]:
                            _accumulate(
                                ing["name"],
                                ing["quantity"],
                                ing["unit"],
                                bool(ing["is_staple"]),
                                ing.get("brand_hint", ""),
                                origin_label,
                            )
                    else:
                        for ing in custom_ings:
                            _accumulate(
                                str(ing.get("name", "")),
                                float(ing.get("quantity", 1) or 1),
                                str(ing.get("unit", "db") or "db"),
                                bool(ing.get("is_staple", False)),
                                str(ing.get("brand_hint", "") or ""),
                                origin_label,
                            )

            for adhoc in plan.get("adhoc_items", []):
                _accumulate(
                    adhoc["name"],
                    adhoc["quantity"],
                    adhoc["unit"],
                    False,
                    adhoc.get("brand_hint", ""),
                    "Chatben kért extra",
                )

        pending_general = [
            item for item in self.list_general_items(include_ordered=False) if item["status"] == "PENDING"
        ]
        in_cart_general = [
            item for item in self.list_general_items(include_ordered=False) if item["status"] == "IN_CART"
        ]

        return {
            "week_start": wk,
            "recipe_and_adhoc_items": list(merged.values()),
            "general_pending_items": [
                {
                    "general_item_id": g["id"],
                    "name": g["name"],
                    "quantity": g["quantity"],
                    "unit": g["unit"],
                    "brand_hint": g["brand_hint"],
                    "preferred_kifli_product": (
                        {
                            "id": prefs_by_key[normalize_key(g["name"])]["kifli_product_id"],
                            "name": prefs_by_key[normalize_key(g["name"])]["kifli_product_name"],
                        }
                        if normalize_key(g["name"]) in prefs_by_key
                        else None
                    ),
                }
                for g in pending_general
            ],
            "general_already_in_cart": in_cart_general,
            "staples_assumed_at_home": sorted(staples_needed),
        }

    # -------------------------------------------------------------------------
    # Chat napló (közös kontextus Telegram és Web között)
    # -------------------------------------------------------------------------
    def add_chat_message(self, role: str, content: str, source: str = "web") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages (role, source, content) VALUES (?, ?, ?)",
                (role, source, content),
            )

    def get_recent_chat_messages(self, limit: int = 16) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, role, source, content, created_at FROM chat_messages ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_chat_history(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chat_messages")

    # -------------------------------------------------------------------------
    # Tervező preferenciák (Büdzsé, Allergének, Sajátmárka, Akciók, Healthy)
    # -------------------------------------------------------------------------
    DEFAULT_PLANNER_SETTINGS: dict[str, Any] = {
        "weekly_budget_ft": 0,  # 0 = nincs felső korlát
        "allergens": [],  # pl. ["laktóz", "glutén", "diófélék", "tojás", "szója", "hal"]
        "prefer_private_label": True,  # Kifli sajátmárkák (Miil, Moddia, Yutto, Ubomi, Dacello, Kitchin)
        "prefer_discounts_and_save_food": True,  # Akciók & Mentsd meg az ételt előnyben
        "min_healthy_score": 3.4,  # Elvárt heti átlag Healthy Score
    }

    def get_planner_settings(self) -> dict[str, Any]:
        result = dict(self.DEFAULT_PLANNER_SETTINGS)
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM planner_settings").fetchall()
            for r in rows:
                if r["key"] in result:
                    try:
                        result[r["key"]] = json.loads(r["value_json"])
                    except Exception:
                        pass
        return result

    def update_planner_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.get_planner_settings()
        with self.connect() as conn:
            for k, v in updates.items():
                if k not in self.DEFAULT_PLANNER_SETTINGS or v is None:
                    continue
                if k == "weekly_budget_ft":
                    v = max(0, int(v))
                elif k == "min_healthy_score":
                    v = max(1.0, min(5.0, round(float(v), 1)))
                elif k in ("prefer_private_label", "prefer_discounts_and_save_food"):
                    v = bool(v)
                elif k == "allergens":
                    v = [str(a).strip().lower() for a in v if str(a).strip()]
                current[k] = v
                conn.execute(
                    """
                    INSERT INTO planner_settings (key, value_json, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = datetime('now')
                    """,
                    (k, json.dumps(v, ensure_ascii=False)),
                )
        return current

    # -------------------------------------------------------------------------
    # Páros Kaja Tinder Match (2 fős valós idejű szinkronizált húzogatás)
    # -------------------------------------------------------------------------
    def create_tinder_session(
        self, meal_type: str = "ebed", target_days: list[str] | None = None
    ) -> dict[str, Any]:
        meal_norm = strip_accents(meal_type.lower().strip())
        if meal_norm not in MEAL_TYPES:
            meal_norm = "ebed"
        days = target_days or ["hetfo", "kedd"]
        # Olvasható 4 karakteres szobakód (O/0/I/1 nélkül)
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(4))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tinder_sessions (code, meal_type, target_days_json)
                VALUES (?, ?, ?)
                """,
                (code, meal_norm, json.dumps(days, ensure_ascii=False)),
            )
        return self.get_tinder_session(code)

    def get_tinder_session(self, code: str) -> dict[str, Any]:
        clean_code = code.strip().upper()
        with self.connect() as conn:
            sess = conn.execute(
                "SELECT * FROM tinder_sessions WHERE code = ?", (clean_code,)
            ).fetchone()
            if not sess:
                raise ValueError(f"Nem található Páros Tinder szoba ezzel a kóddal: {clean_code}")
            swipes = conn.execute(
                "SELECT user_slot, recipe_id, decision, swiped_at FROM tinder_swipes WHERE session_code = ?",
                (clean_code,),
            ).fetchall()

        p1_likes: set[int] = set()
        p2_likes: set[int] = set()
        p1_swiped: list[int] = []
        p2_swiped: list[int] = []
        for s in swipes:
            rid = int(s["recipe_id"])
            if s["user_slot"] == "p1":
                p1_swiped.append(rid)
                if s["decision"] == "like":
                    p1_likes.add(rid)
            else:
                p2_swiped.append(rid)
                if s["decision"] == "like":
                    p2_likes.add(rid)

        matched_ids = sorted(p1_likes.intersection(p2_likes))
        recipes_by_id = {r["id"]: r for r in self.list_recipes()}
        matched_recipes = [recipes_by_id[rid] for rid in matched_ids if rid in recipes_by_id]

        return {
            "code": sess["code"],
            "meal_type": sess["meal_type"],
            "target_days": json.loads(sess["target_days_json"]),
            "created_at": sess["created_at"],
            "p1_swiped_ids": p1_swiped,
            "p2_swiped_ids": p2_swiped,
            "p1_like_count": len(p1_likes),
            "p2_like_count": len(p2_likes),
            "matches": matched_recipes,
        }

    def record_tinder_swipe(
        self, code: str, user_slot: str, recipe_id: int, decision: str
    ) -> dict[str, Any]:
        clean_code = code.strip().upper()
        slot = "p1" if user_slot.strip().lower() == "p1" else "p2"
        dec = "like" if decision.strip().lower() == "like" else "pass"

        with self.connect() as conn:
            sess = conn.execute(
                "SELECT code FROM tinder_sessions WHERE code = ?", (clean_code,)
            ).fetchone()
            if not sess:
                raise ValueError(f"Nem található Páros Tinder szoba: {clean_code}")
            conn.execute(
                """
                INSERT INTO tinder_swipes (session_code, user_slot, recipe_id, decision, swiped_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(session_code, user_slot, recipe_id) DO UPDATE SET
                    decision = excluded.decision,
                    swiped_at = datetime('now')
                """,
                (clean_code, slot, int(recipe_id), dec),
            )

        state = self.get_tinder_session(clean_code)
        is_match = dec == "like" and any(m["id"] == int(recipe_id) for m in state["matches"])
        matched_recipe = (
            next((m for m in state["matches"] if m["id"] == int(recipe_id)), None)
            if is_match
            else None
        )
        return {
            "is_match": is_match,
            "matched_recipe": matched_recipe,
            "session": state,
        }
