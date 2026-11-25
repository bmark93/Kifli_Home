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

DAIRY_KEYWORDS = (
    "tej",
    "tejföl",
    "tejszín",
    "vaj",
    "túró",
    "sajt",
    "trappista",
    "gouda",
    "joghurt",
    "kefir",
    "mascarpone",
    "mozzarella",
    "krémsajt",
    "cheddar",
    "feta",
    "camembert",
    "parmezán",
    "tejszínhab",
    "ricotta",
)

GLUTEN_KEYWORDS = (
    "tészta",
    "spagetti",
    "penne",
    "fusilli",
    "nokedli",
    "kenyér",
    "zsemle",
    "kifli",
    "liszt",
    "zsemlemorzsa",
    "tortilla",
    "pita",
    "kuszkusz",
    "bulgur",
    "keksz",
)


def normalize_key(text: str) -> str:
    """Kisbetűs, szóköz-normalizált kulcs hozzávaló összevonáshoz és kedvenc márkákhoz."""
    return " ".join(text.strip().lower().split())


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def current_week_monday(today: dt.date | None = None) -> str:
    d = today or dt.date.today()
    monday = d - dt.timedelta(days=d.weekday())
    return monday.isoformat()


def detect_diet_requirements(ingredient_name: str, active_allergens: list[str]) -> list[str]:
    """
    Ha laktóz/glutén szűrő aktív, a tejtermékeket és gluténos tésztákat/kenyereket
    NEM kihagyja, hanem 'laktózmentes' / 'gluténmentes' helyettesítő címkével látja el!
    """
    low = normalize_key(ingredient_name)
    allergs = {a.strip().lower() for a in active_allergens}
    tags: list[str] = []

    if "laktóz" in allergs:
        is_plant_based = any(
            w in low
            for w in ("laktózmentes", "növényi", "zabital", "mandula", "kókusz", "rizsital", "szójaital")
        )
        if not is_plant_based and any(k in low for k in DAIRY_KEYWORDS):
            tags.append("laktózmentes")

    if "glutén" in allergs:
        if "gluténmentes" not in low and any(k in low for k in GLUTEN_KEYWORDS):
            tags.append("gluténmentes")

    return tags


class Database:
    DEFAULT_PLANNER_SETTINGS: dict[str, Any] = {
        "household_size": 2,
        "plan_days": 7,
        "days_per_meal": 2,
        "weekly_budget_ft": 0,
        "allergens": [],
        "prefer_private_label": True,
        "prefer_discounts_and_save_food": True,
        "min_healthy_score": 3.4,
        "ai_recommendations_enabled": True,
        "ai_recommendation_count": 1,
        "ai_recommendation_meals": ["ebed"],
    }

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

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    llm_provider TEXT NOT NULL DEFAULT '',
                    llm_model TEXT NOT NULL DEFAULT '',
                    llm_base_url TEXT NOT NULL DEFAULT '',
                    llm_api_key_enc TEXT NOT NULL DEFAULT '',
                    mcp_token TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS ai_usage_daily (
                    user_id INTEGER NOT NULL,
                    day_iso TEXT NOT NULL,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, day_iso)
                );

                CREATE TABLE IF NOT EXISTS recipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    title TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    servings INTEGER NOT NULL DEFAULT 2,
                    instructions TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    healthy_score INTEGER NOT NULL DEFAULT 3,
                    kcal_per_serving INTEGER NOT NULL DEFAULT 0,
                    protein_g REAL NOT NULL DEFAULT 0,
                    carbs_g REAL NOT NULL DEFAULT 0,
                    fat_g REAL NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS general_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
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
                    user_id INTEGER NOT NULL DEFAULT 1,
                    key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS product_preferences (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    ingredient_key TEXT NOT NULL,
                    ingredient_label TEXT NOT NULL,
                    kifli_product_id TEXT NOT NULL,
                    kifli_product_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, ingredient_key)
                );

                CREATE TABLE IF NOT EXISTS weekly_plans (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    week_start TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'IN_CART', 'ORDERED')),
                    plan_json TEXT NOT NULL,
                    adhoc_items_json TEXT NOT NULL DEFAULT '[]',
                    recommendation_note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, week_start)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    source TEXT NOT NULL DEFAULT 'web',
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS processed_kifli_orders (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    order_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, order_id)
                );

                CREATE TABLE IF NOT EXISTS planner_settings (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, key)
                );

                CREATE TABLE IF NOT EXISTS tinder_sessions (
                    code TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL DEFAULT 1,
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

            # Zökkenőmentes migráció régi 1-useres NAS adatbázisról Multi-User sémára (0 adatvesztés!)
            self._migrate_legacy_tables(conn)

            # Alap user_id=1 kezdő adatok, ha teljesen üres a DB
            existing_staples = conn.execute(
                "SELECT COUNT(*) AS c FROM staples WHERE user_id = 1"
            ).fetchone()["c"]
            if existing_staples == 0:
                self._seed_default_staples(conn, user_id=1)

            existing_recipes = conn.execute(
                "SELECT COUNT(*) AS c FROM recipes WHERE user_id = 1"
            ).fetchone()["c"]
            if existing_recipes == 0:
                self._seed_starter_recipes(conn, user_id=1)

    def _migrate_legacy_tables(self, conn: sqlite3.Connection) -> None:
        recipe_cols = self._table_columns(conn, "recipes")
        if "image_url" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        if "healthy_score" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN healthy_score INTEGER NOT NULL DEFAULT 3")
        if "kcal_per_serving" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN kcal_per_serving INTEGER NOT NULL DEFAULT 0")
        if "protein_g" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN protein_g REAL NOT NULL DEFAULT 0")
        if "carbs_g" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN carbs_g REAL NOT NULL DEFAULT 0")
        if "fat_g" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN fat_g REAL NOT NULL DEFAULT 0")
        if "user_id" not in recipe_cols:
            conn.execute("ALTER TABLE recipes ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

        if "user_id" not in self._table_columns(conn, "general_items"):
            conn.execute("ALTER TABLE general_items ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

        if "user_id" not in self._table_columns(conn, "chat_messages"):
            conn.execute("ALTER TABLE chat_messages ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

        if "owner_user_id" not in self._table_columns(conn, "tinder_sessions"):
            conn.execute(
                "ALTER TABLE tinder_sessions ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 1"
            )

        # Kompozit PK-s táblák átépítése, ha még nincs user_id oszlopuk
        if "user_id" not in self._table_columns(conn, "staples"):
            conn.executescript(
                """
                CREATE TABLE staples_v2 (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );
                INSERT OR IGNORE INTO staples_v2 (user_id, key, display_name)
                SELECT 1, key, display_name FROM staples;
                DROP TABLE staples;
                ALTER TABLE staples_v2 RENAME TO staples;
                """
            )

        if "user_id" not in self._table_columns(conn, "product_preferences"):
            conn.executescript(
                """
                CREATE TABLE product_preferences_v2 (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    ingredient_key TEXT NOT NULL,
                    ingredient_label TEXT NOT NULL,
                    kifli_product_id TEXT NOT NULL,
                    kifli_product_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, ingredient_key)
                );
                INSERT OR IGNORE INTO product_preferences_v2
                    (user_id, ingredient_key, ingredient_label, kifli_product_id, kifli_product_name, updated_at)
                SELECT 1, ingredient_key, ingredient_label, kifli_product_id, kifli_product_name, updated_at
                FROM product_preferences;
                DROP TABLE product_preferences;
                ALTER TABLE product_preferences_v2 RENAME TO product_preferences;
                """
            )

        if "user_id" not in self._table_columns(conn, "weekly_plans"):
            conn.executescript(
                """
                CREATE TABLE weekly_plans_v2 (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    week_start TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'IN_CART', 'ORDERED')),
                    plan_json TEXT NOT NULL,
                    adhoc_items_json TEXT NOT NULL DEFAULT '[]',
                    recommendation_note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, week_start)
                );
                INSERT OR IGNORE INTO weekly_plans_v2
                    (user_id, week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at)
                SELECT 1, week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at
                FROM weekly_plans;
                DROP TABLE weekly_plans;
                ALTER TABLE weekly_plans_v2 RENAME TO weekly_plans;
                """
            )

        if "user_id" not in self._table_columns(conn, "planner_settings"):
            conn.executescript(
                """
                CREATE TABLE planner_settings_v2 (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, key)
                );
                INSERT OR IGNORE INTO planner_settings_v2 (user_id, key, value_json, updated_at)
                SELECT 1, key, value_json, updated_at FROM planner_settings;
                DROP TABLE planner_settings;
                ALTER TABLE planner_settings_v2 RENAME TO planner_settings;
                """
            )

        if "user_id" not in self._table_columns(conn, "processed_kifli_orders"):
            conn.executescript(
                """
                CREATE TABLE processed_kifli_orders_v2 (
                    user_id INTEGER NOT NULL DEFAULT 1,
                    order_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, order_id)
                );
                INSERT OR IGNORE INTO processed_kifli_orders_v2 (user_id, order_id, processed_at)
                SELECT 1, order_id, processed_at FROM processed_kifli_orders;
                DROP TABLE processed_kifli_orders;
                ALTER TABLE processed_kifli_orders_v2 RENAME TO processed_kifli_orders;
                """
            )

    def _seed_default_staples(self, conn: sqlite3.Connection, user_id: int) -> None:
        for item in DEFAULT_STAPLES:
            conn.execute(
                "INSERT OR IGNORE INTO staples (user_id, key, display_name) VALUES (?, ?, ?)",
                (user_id, normalize_key(item), item),
            )

    def _seed_starter_recipes(self, conn: sqlite3.Connection, user_id: int) -> list[int]:
        starters = [
            {
                "title": "Zabkása banánnal és áfonyával",
                "categories": ["reggeli"],
                "servings": 2,
                "healthy_score": 5,
                "kcal_per_serving": 390,
                "protein_g": 12.0,
                "carbs_g": 68.0,
                "fat_g": 7.0,
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
                "healthy_score": 4,
                "kcal_per_serving": 480,
                "protein_g": 34.0,
                "carbs_g": 26.0,
                "fat_g": 26.0,
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
                "healthy_score": 3,
                "kcal_per_serving": 640,
                "protein_g": 46.0,
                "carbs_g": 58.0,
                "fat_g": 23.0,
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
                "healthy_score": 3,
                "kcal_per_serving": 690,
                "protein_g": 38.0,
                "carbs_g": 74.0,
                "fat_g": 25.0,
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
                "healthy_score": 5,
                "kcal_per_serving": 460,
                "protein_g": 44.0,
                "carbs_g": 14.0,
                "fat_g": 24.0,
                "instructions": "Ropogós római saláta pirított csirkemellcsíkokkal és parmezánnal.",
                "ingredients": [
                    {"name": "római saláta", "quantity": 1, "unit": "db", "is_staple": False},
                    {"name": "csirkemell filé", "quantity": 400, "unit": "g", "is_staple": False},
                    {"name": "cézár öntet", "quantity": 1, "unit": "üveg", "is_staple": False},
                    {"name": "parmezán sajt", "quantity": 50, "unit": "g", "is_staple": False},
                ],
            },
        ]
        created_ids: list[int] = []
        for r in starters:
            cur = conn.execute(
                """
                INSERT INTO recipes (user_id, title, categories_json, servings, instructions, healthy_score, kcal_per_serving, protein_g, carbs_g, fat_g)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    r["title"],
                    json.dumps(r["categories"], ensure_ascii=False),
                    r["servings"],
                    r["instructions"],
                    r["healthy_score"],
                    r["kcal_per_serving"],
                    r["protein_g"],
                    r["carbs_g"],
                    r["fat_g"],
                ),
            )
            recipe_id = int(cur.lastrowid)
            created_ids.append(recipe_id)
            for ing in r["ingredients"]:
                conn.execute(
                    """
                    INSERT INTO recipe_ingredients (recipe_id, name, quantity, unit, is_staple, brand_hint)
                    VALUES (?, ?, ?, ?, ?, '')
                    """,
                    (recipe_id, ing["name"], ing["quantity"], ing["unit"], 1 if ing["is_staple"] else 0),
                )
        return created_ids

    # -------------------------------------------------------------------------
    # Felhasználók (Multi-User + BYOK + Demo Sandbox + Napi AI limit)
    # -------------------------------------------------------------------------
    def count_real_users(self) -> int:
        with self.connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) AS c FROM users WHERE is_demo = 0").fetchone()["c"]
            )

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE lower(trim(email)) = lower(trim(?))", (email,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_mcp_token(self, token: str) -> dict[str, Any] | None:
        clean = (token or "").strip()
        if not clean:
            return None
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE mcp_token = ?", (clean,)).fetchone()
            return dict(row) if row else None

    def create_user(
        self,
        email: str,
        display_name: str,
        password_hash: str,
        is_admin: bool = False,
        is_demo: bool = False,
        mcp_token: str = "",
        force_id: int | None = None,
    ) -> dict[str, Any]:
        clean_email = email.strip().lower()
        clean_name = display_name.strip() or clean_email.split("@")[0]
        with self.connect() as conn:
            if force_id is not None:
                cur = conn.execute(
                    """
                    INSERT INTO users (id, email, display_name, password_hash, is_admin, is_demo, mcp_token)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        force_id,
                        clean_email,
                        clean_name,
                        password_hash,
                        1 if is_admin else 0,
                        1 if is_demo else 0,
                        mcp_token,
                    ),
                )
                uid = force_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO users (email, display_name, password_hash, is_admin, is_demo, mcp_token)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_email,
                        clean_name,
                        password_hash,
                        1 if is_admin else 0,
                        1 if is_demo else 0,
                        mcp_token,
                    ),
                )
                uid = int(cur.lastrowid)

            # Új felhasználónak alap kamra-lista + 5 kezdő recept, ha még nincs neki
            has_staples = conn.execute(
                "SELECT COUNT(*) AS c FROM staples WHERE user_id = ?", (uid,)
            ).fetchone()["c"]
            if has_staples == 0:
                self._seed_default_staples(conn, uid)

            has_recipes = conn.execute(
                "SELECT COUNT(*) AS c FROM recipes WHERE user_id = ?", (uid,)
            ).fetchone()["c"]
            if has_recipes == 0:
                self._seed_starter_recipes(conn, uid)

        return self.get_user_by_id(uid) or {}

    def update_user_llm_settings(
        self,
        user_id: int,
        llm_provider: str,
        llm_model: str,
        llm_base_url: str = "",
        llm_api_key_enc: str | None = None,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            if llm_api_key_enc is None:
                conn.execute(
                    """
                    UPDATE users
                    SET llm_provider = ?, llm_model = ?, llm_base_url = ?
                    WHERE id = ?
                    """,
                    (llm_provider.strip().lower(), llm_model.strip(), llm_base_url.strip(), user_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE users
                    SET llm_provider = ?, llm_model = ?, llm_base_url = ?, llm_api_key_enc = ?
                    WHERE id = ?
                    """,
                    (
                        llm_provider.strip().lower(),
                        llm_model.strip(),
                        llm_base_url.strip(),
                        llm_api_key_enc,
                        user_id,
                    ),
                )
        return self.get_user_by_id(user_id) or {}

    def rotate_user_mcp_token(self, user_id: int, new_token: str) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute("UPDATE users SET mcp_token = ? WHERE id = ?", (new_token, user_id))
        return self.get_user_by_id(user_id) or {}

    def ensure_demo_user(self, password_hash: str, mcp_token: str) -> dict[str, Any]:
        existing = self.get_user_by_email("demo@kifli.otthon")
        if existing:
            return existing

        # Ha még nincs 1-es user (első indítás), a demo user kapjon >= 2-es ID-t, hogy az 1-es maradjon a tulajé!
        with self.connect() as conn:
            max_id = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM users").fetchone()["m"]
            target_id = max(2, int(max_id) + 1)

        demo = self.create_user(
            email="demo@kifli.otthon",
            display_name="Kifli Demo Vendég",
            password_hash=password_hash,
            is_admin=False,
            is_demo=True,
            mcp_token=mcp_token,
            force_id=target_id,
        )
        uid = int(demo["id"])

        # Gazdag demó tartalom: 2 kedvenc termék (hogy a Sajátmárka popup azonnal éljen!),
        # 2 háztartási tétel és egy kész heti menü!
        self.save_product_preference("tej 2,8%", "16321", "Magyar Tej ESL Tej 2,8%", user_id=uid)
        self.save_product_preference(
            "papírzsebkendő", "97249", "Zewa Deluxe Camomile 3 rétegű papírzsebkendő", user_id=uid
        )
        self.add_general_item("Papírzsebkendő", 1, "csomag", "Zewa Deluxe", user_id=uid)
        self.add_general_item("Mosogatógép kapszula", 1, "csomag", "Finish Quantum", user_id=uid)

        demo_recipes = self.list_recipes(user_id=uid)
        by_title = {r["title"]: r for r in demo_recipes}
        zab = by_title.get("Zabkása banánnal és áfonyával")
        rant = by_title.get("Sonkás-sajtos rántotta kovászos kenyérrel")
        pap = by_title.get("Csirkepaprikás nokedlivel")
        bol = by_title.get("Bolognai spagetti parmezánnal")
        cez = by_title.get("Cézár saláta grillezett csirkével")

        if zab and rant and pap and bol and cez:
            self.set_weekly_meal_slots_manual(["hetfo", "kedd", "pentek"], "reggeli", recipe_id=zab["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["szerda", "csutortok", "szombat", "vasarnap"], "reggeli", recipe_id=rant["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["hetfo", "kedd"], "ebed", recipe_id=pap["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["szerda", "csutortok"], "ebed", recipe_id=bol["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["pentek", "szombat"], "ebed", recipe_id=cez["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["hetfo", "szerda", "pentek"], "vacsora", recipe_id=cez["id"], user_id=uid)
            self.set_weekly_meal_slots_manual(["kedd", "csutortok", "vasarnap"], "vacsora", recipe_id=rant["id"], user_id=uid)

        self.update_planner_settings({"weekly_budget_ft": 45000}, user_id=uid)
        return demo

    def get_daily_ai_usage(self, user_id: int) -> int:
        today_iso = dt.date.today().isoformat()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT call_count FROM ai_usage_daily WHERE user_id = ? AND day_iso = ?",
                (int(user_id), today_iso),
            ).fetchone()
            return int(row["call_count"]) if row else 0

    def increment_daily_ai_usage(self, user_id: int) -> int:
        today_iso = dt.date.today().isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_usage_daily (user_id, day_iso, call_count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, day_iso) DO UPDATE SET
                    call_count = call_count + 1
                """,
                (int(user_id), today_iso),
            )
            row = conn.execute(
                "SELECT call_count FROM ai_usage_daily WHERE user_id = ? AND day_iso = ?",
                (int(user_id), today_iso),
            ).fetchone()
            return int(row["call_count"])

    # -------------------------------------------------------------------------
    # Receptek
    # -------------------------------------------------------------------------
    def list_recipes(self, category: str | None = None, user_id: int = 1) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM recipes WHERE user_id = ? ORDER BY title COLLATE NOCASE",
                (int(user_id),),
            ).fetchall()
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
                        "kcal_per_serving": max(0, int(row["kcal_per_serving"] or 0)),
                        "protein_g": round(max(0.0, float(row["protein_g"] or 0)), 1),
                        "carbs_g": round(max(0.0, float(row["carbs_g"] or 0)), 1),
                        "fat_g": round(max(0.0, float(row["fat_g"] or 0)), 1),
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
        kcal_per_serving: int | None = None,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
        user_id: int = 1,
    ) -> dict[str, Any]:
        valid_cats = [c for c in categories if c in MEAL_TYPES] or ["ebed"]
        clamped_score = max(1, min(5, int(healthy_score or 3)))
        staples_set = {s["key"] for s in self.list_staples(user_id=user_id)}
        with self.connect() as conn:
            if recipe_id is not None:
                prev = conn.execute(
                    "SELECT image_url, kcal_per_serving, protein_g, carbs_g, fat_g FROM recipes WHERE id = ? AND user_id = ?",
                    (recipe_id, int(user_id)),
                ).fetchone()
                if not prev:
                    raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
                final_image_url = prev["image_url"] if image_url is None else image_url.strip()
                final_kcal = (
                    int(prev["kcal_per_serving"] or 0)
                    if kcal_per_serving is None
                    else max(0, int(kcal_per_serving))
                )
                final_protein = (
                    float(prev["protein_g"] or 0)
                    if protein_g is None
                    else round(max(0.0, float(protein_g)), 1)
                )
                final_carbs = (
                    float(prev["carbs_g"] or 0)
                    if carbs_g is None
                    else round(max(0.0, float(carbs_g)), 1)
                )
                final_fat = (
                    float(prev["fat_g"] or 0)
                    if fat_g is None
                    else round(max(0.0, float(fat_g)), 1)
                )

                conn.execute(
                    """
                    UPDATE recipes
                    SET title = ?, categories_json = ?, servings = ?, instructions = ?, source_url = ?,
                        image_url = ?, healthy_score = ?, kcal_per_serving = ?, protein_g = ?, carbs_g = ?, fat_g = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (
                        title.strip(),
                        json.dumps(valid_cats, ensure_ascii=False),
                        max(1, int(servings)),
                        instructions.strip(),
                        source_url.strip(),
                        final_image_url,
                        clamped_score,
                        final_kcal,
                        final_protein,
                        final_carbs,
                        final_fat,
                        recipe_id,
                        int(user_id),
                    ),
                )
                conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (recipe_id,))
                rid = recipe_id
            else:
                cur = conn.execute(
                    """
                    INSERT INTO recipes (user_id, title, categories_json, servings, instructions, source_url, image_url, healthy_score, kcal_per_serving, protein_g, carbs_g, fat_g)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(user_id),
                        title.strip(),
                        json.dumps(valid_cats, ensure_ascii=False),
                        max(1, int(servings)),
                        instructions.strip(),
                        source_url.strip(),
                        (image_url or "").strip(),
                        clamped_score,
                        max(0, int(kcal_per_serving or 0)),
                        round(max(0.0, float(protein_g or 0)), 1),
                        round(max(0.0, float(carbs_g or 0)), 1),
                        round(max(0.0, float(fat_g or 0)), 1),
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
        matches = [r for r in self.list_recipes(user_id=user_id) if r["id"] == rid]
        return matches[0]

    def set_recipe_image(self, recipe_id: int, image_url: str, user_id: int = 1) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE recipes SET image_url = ? WHERE id = ? AND user_id = ?",
                (image_url.strip(), int(recipe_id), int(user_id)),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
        return [r for r in self.list_recipes(user_id=user_id) if r["id"] == int(recipe_id)][0]

    def set_recipe_healthy_score(
        self, recipe_id: int, healthy_score: int, user_id: int = 1
    ) -> dict[str, Any]:
        clamped = max(1, min(5, int(healthy_score)))
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE recipes SET healthy_score = ? WHERE id = ? AND user_id = ?",
                (clamped, int(recipe_id), int(user_id)),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
        return [r for r in self.list_recipes(user_id=user_id) if r["id"] == int(recipe_id)][0]

    def set_recipe_macros(
        self,
        recipe_id: int,
        kcal_per_serving: int,
        protein_g: float,
        carbs_g: float,
        fat_g: float,
        user_id: int = 1,
    ) -> dict[str, Any]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE recipes
                SET kcal_per_serving = ?, protein_g = ?, carbs_g = ?, fat_g = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    max(0, int(kcal_per_serving)),
                    round(max(0.0, float(protein_g)), 1),
                    round(max(0.0, float(carbs_g)), 1),
                    round(max(0.0, float(fat_g)), 1),
                    int(recipe_id),
                    int(user_id),
                ),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Nem található recept ezzel az ID-val: {recipe_id}")
        return [r for r in self.list_recipes(user_id=user_id) if r["id"] == int(recipe_id)][0]

    def delete_recipe(self, recipe_id: int, user_id: int = 1) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM recipes WHERE id = ? AND user_id = ?", (recipe_id, int(user_id))
            )
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Általános / Háztartási egyszeri lista (Anti-loop állapotgéppel!)
    # -------------------------------------------------------------------------
    def list_general_items(
        self, include_ordered: bool = False, user_id: int = 1
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if include_ordered:
                rows = conn.execute(
                    "SELECT * FROM general_items WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
                    (int(user_id),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM general_items WHERE user_id = ? AND status IN ('PENDING', 'IN_CART') ORDER BY status DESC, id ASC",
                    (int(user_id),),
                ).fetchall()
            return [dict(r) for r in rows]

    def add_general_item(
        self,
        name: str,
        quantity: float = 1.0,
        unit: str = "db",
        brand_hint: str = "",
        user_id: int = 1,
    ) -> dict[str, Any]:
        clean_name = name.strip()
        clean_unit = (unit or "db").strip()
        clean_brand = (brand_hint or "").strip()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM general_items
                WHERE user_id = ?
                  AND status = 'PENDING'
                  AND lower(trim(name)) = lower(?)
                  AND lower(trim(unit)) = lower(?)
                  AND lower(trim(brand_hint)) = lower(?)
                """,
                (int(user_id), clean_name, clean_unit, clean_brand),
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
                    INSERT INTO general_items (user_id, name, quantity, unit, brand_hint, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (int(user_id), clean_name, float(quantity), clean_unit, clean_brand),
                )
                item_id = int(cur.lastrowid)
            row = conn.execute("SELECT * FROM general_items WHERE id = ?", (item_id,)).fetchone()
            return dict(row)

    def mark_general_items_in_cart(
        self, carted_items: list[dict[str, Any]], user_id: int = 1
    ) -> list[dict[str, Any]]:
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
                    WHERE id = ? AND user_id = ? AND status = 'PENDING'
                    """,
                    (pid, pname, now_iso, item_id, int(user_id)),
                )
                row = conn.execute(
                    "SELECT * FROM general_items WHERE id = ? AND user_id = ?",
                    (item_id, int(user_id)),
                ).fetchone()
                if row:
                    updated.append(dict(row))
        return updated

    def finalize_order_and_clear_general_items(
        self,
        kifli_order_id: str | None = None,
        include_pending_if_forced: bool = False,
        user_id: int = 1,
    ) -> dict[str, Any]:
        now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
        with self.connect() as conn:
            if kifli_order_id:
                already = conn.execute(
                    "SELECT 1 FROM processed_kifli_orders WHERE user_id = ? AND order_id = ?",
                    (int(user_id), str(kifli_order_id)),
                ).fetchone()
                if already:
                    return {"cleared_count": 0, "already_processed": True}
                conn.execute(
                    "INSERT INTO processed_kifli_orders (user_id, order_id, processed_at) VALUES (?, ?, ?)",
                    (int(user_id), str(kifli_order_id), now_iso),
                )

            target_statuses = ("IN_CART", "PENDING") if include_pending_if_forced else ("IN_CART",)
            placeholders = ",".join("?" for _ in target_statuses)
            rows = conn.execute(
                f"SELECT id, name, brand_hint FROM general_items WHERE user_id = ? AND status IN ({placeholders})",
                (int(user_id), *target_statuses),
            ).fetchall()
            cleared_items = [dict(r) for r in rows]

            conn.execute(
                f"""
                UPDATE general_items
                SET status = 'ORDERED', ordered_at = ?
                WHERE user_id = ? AND status IN ({placeholders})
                """,
                (now_iso, int(user_id), *target_statuses),
            )

            week_key = current_week_monday()
            conn.execute(
                """
                UPDATE weekly_plans
                SET status = 'ORDERED', adhoc_items_json = '[]', updated_at = ?
                WHERE user_id = ? AND week_start = ?
                """,
                (now_iso, int(user_id), week_key),
            )
            return {
                "cleared_count": len(cleared_items),
                "cleared_items": cleared_items,
                "already_processed": False,
            }

    def revert_in_cart_general_items_to_pending(self, user_id: int = 1) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE general_items
                SET status = 'PENDING', carted_at = NULL
                WHERE user_id = ? AND status = 'IN_CART'
                """,
                (int(user_id),),
            )
            return cur.rowcount

    def delete_general_item(self, item_id: int, user_id: int = 1) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM general_items WHERE id = ? AND user_id = ?",
                (item_id, int(user_id)),
            )
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Kamra-alapanyagok & Kedvenc Kifli márkák memóriája
    # -------------------------------------------------------------------------
    def list_staples(self, user_id: int = 1) -> list[dict[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, display_name FROM staples WHERE user_id = ? ORDER BY display_name",
                (int(user_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_staple(self, name: str, user_id: int = 1) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO staples (user_id, key, display_name) VALUES (?, ?, ?)",
                (int(user_id), normalize_key(name), name.strip()),
            )

    def delete_staple(self, key: str, user_id: int = 1) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM staples WHERE user_id = ? AND key = ?",
                (int(user_id), normalize_key(key)),
            )
            return cur.rowcount > 0

    def list_product_preferences(self, user_id: int = 1) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM product_preferences WHERE user_id = ? ORDER BY ingredient_label COLLATE NOCASE",
                (int(user_id),),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_product_preference(
        self,
        ingredient_name: str,
        kifli_product_id: str,
        kifli_product_name: str,
        user_id: int = 1,
    ) -> dict[str, Any]:
        key = normalize_key(ingredient_name)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO product_preferences (user_id, ingredient_key, ingredient_label, kifli_product_id, kifli_product_name, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id, ingredient_key) DO UPDATE SET
                    ingredient_label = excluded.ingredient_label,
                    kifli_product_id = excluded.kifli_product_id,
                    kifli_product_name = excluded.kifli_product_name,
                    updated_at = datetime('now')
                """,
                (
                    int(user_id),
                    key,
                    ingredient_name.strip(),
                    str(kifli_product_id).strip(),
                    kifli_product_name.strip(),
                ),
            )
            row = conn.execute(
                "SELECT * FROM product_preferences WHERE user_id = ? AND ingredient_key = ?",
                (int(user_id), key),
            ).fetchone()
            return dict(row)

    def delete_product_preference(self, ingredient_key: str, user_id: int = 1) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM product_preferences WHERE user_id = ? AND ingredient_key = ?",
                (int(user_id), normalize_key(ingredient_key)),
            )
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Heti Menüterv & Összesített Bevásárlólista
    # -------------------------------------------------------------------------
    def get_weekly_plan(
        self, week_start: str | None = None, user_id: int = 1
    ) -> dict[str, Any] | None:
        wk = week_start or current_week_monday()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM weekly_plans WHERE user_id = ? AND week_start = ?",
                (int(user_id), wk),
            ).fetchone()
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
        user_id: int = 1,
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        existing = self.get_weekly_plan(wk, user_id=user_id)
        final_adhoc = (
            adhoc_items
            if adhoc_items is not None
            else (existing["adhoc_items"] if existing else [])
        )
        final_note = recommendation_note or (existing["recommendation_note"] if existing else "")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans (user_id, week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id, week_start) DO UPDATE SET
                    status = excluded.status,
                    plan_json = excluded.plan_json,
                    adhoc_items_json = excluded.adhoc_items_json,
                    recommendation_note = excluded.recommendation_note,
                    updated_at = datetime('now')
                """,
                (
                    int(user_id),
                    wk,
                    status,
                    json.dumps(days, ensure_ascii=False),
                    json.dumps(final_adhoc, ensure_ascii=False),
                    final_note,
                ),
            )
        return self.get_weekly_plan(wk, user_id=user_id) or {}

    def update_weekly_meal_slot(
        self,
        day_key: str,
        meal_type: str,
        title: str,
        recipe_id: int | None = None,
        is_recommendation: bool = False,
        custom_ingredients: list[dict[str, Any]] | None = None,
        week_start: str | None = None,
        user_id: int = 1,
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk, user_id=user_id)
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
        return self.save_weekly_plan(days=days, week_start=wk, user_id=user_id)

    def set_weekly_meal_slots_manual(
        self,
        day_keys: list[str],
        meal_type: str,
        recipe_id: int | None = None,
        custom_title: str = "",
        clear: bool = False,
        week_start: str | None = None,
        user_id: int = 1,
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk, user_id=user_id)
        days = plan["days"] if plan else {d[0]: {} for d in DAYS_HU}
        valid_day_keys = {d[0] for d in DAYS_HU}
        meal_norm = strip_accents(meal_type.lower().strip())
        if meal_norm not in MEAL_TYPES:
            raise ValueError(f"Ismeretlen étkezés: {meal_type}")

        resolved_title = custom_title.strip()
        if recipe_id is not None:
            matches = [r for r in self.list_recipes(user_id=user_id) if r["id"] == int(recipe_id)]
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
        return self.save_weekly_plan(days=days, week_start=wk, user_id=user_id)

    def reset_weekly_plan(self, week_start: str | None = None, user_id: int = 1) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        empty_days = {d[0]: {} for d in DAYS_HU}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO weekly_plans (user_id, week_start, status, plan_json, adhoc_items_json, recommendation_note, updated_at)
                VALUES (?, ?, 'DRAFT', ?, '[]', '', datetime('now'))
                ON CONFLICT(user_id, week_start) DO UPDATE SET
                    status = 'DRAFT',
                    plan_json = excluded.plan_json,
                    adhoc_items_json = '[]',
                    recommendation_note = '',
                    updated_at = datetime('now')
                """,
                (int(user_id), wk, json.dumps(empty_days, ensure_ascii=False)),
            )
        return self.get_weekly_plan(wk, user_id=user_id) or {}

    def add_adhoc_item_to_week(
        self,
        name: str,
        quantity: float = 1.0,
        unit: str = "db",
        brand_hint: str = "",
        week_start: str | None = None,
        user_id: int = 1,
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk, user_id=user_id)
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
        return self.save_weekly_plan(days=days, week_start=wk, adhoc_items=adhoc, user_id=user_id)

    def aggregate_shopping_list(
        self, week_start: str | None = None, user_id: int = 1
    ) -> dict[str, Any]:
        wk = week_start or current_week_monday()
        plan = self.get_weekly_plan(wk, user_id=user_id)
        recipes_by_id = {r["id"]: r for r in self.list_recipes(user_id=user_id)}
        staples_keys = {s["key"] for s in self.list_staples(user_id=user_id)}
        prefs_by_key = {p["ingredient_key"]: p for p in self.list_product_preferences(user_id=user_id)}
        planner_prefs = self.get_planner_settings(user_id=user_id)
        active_allergens = planner_prefs.get("allergens") or []

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
            diet_tags = detect_diet_requirements(name, active_allergens)
            bucket_key = (nkey, ukey)
            if bucket_key not in merged:
                pref = prefs_by_key.get(nkey)
                pref_ok = pref is not None
                if pref and diet_tags:
                    pname_low = pref["kifli_product_name"].lower()
                    if any(dt not in pname_low for dt in diet_tags):
                        pref_ok = False
                search_hint = f"{' '.join(diet_tags)} {name.strip()}".strip() if diet_tags else name.strip()
                merged[bucket_key] = {
                    "name": name.strip(),
                    "quantity": float(qty),
                    "unit": unit.strip() or "db",
                    "brand_hint": brand_hint.strip(),
                    "diet_tags": diet_tags,
                    "search_hint": search_hint,
                    "preferred_kifli_product": (
                        {
                            "id": pref["kifli_product_id"],
                            "name": pref["kifli_product_name"],
                        }
                        if (pref and pref_ok)
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
            household_size = max(1, int(planner_prefs.get("household_size", 2) or 2))
            plan_days_count = max(1, min(7, int(planner_prefs.get("plan_days", 7) or 7)))
            days_per_meal = max(1, min(4, int(planner_prefs.get("days_per_meal", 2) or 2)))
            active_days = DAYS_HU[:plan_days_count]

            # Batch-cooking követés: (title_key, start_day_idx, remaining_covered_days)
            batch_state: dict[str, tuple[str, int, int]] = {}
            for day_idx, (day_code, day_label) in enumerate(active_days):
                day_slots = plan["days"].get(day_code, {})
                for meal_code in MEAL_TYPES:
                    slot = day_slots.get(meal_code)
                    if not slot:
                        batch_state.pop(meal_code, None)
                        continue
                    rid = slot.get("recipe_id")
                    title_key = str(rid) if rid else normalize_key(slot.get("title", ""))
                    rec_obj = recipes_by_id.get(rid) if rid else None
                    servings = max(1, int(rec_obj["servings"])) if rec_obj else household_size

                    # Ha a recept adagszáma legalább 2x a háztartás mérete és days_per_meal > 1
                    covered_days = min(days_per_meal, max(1, servings // household_size))
                    if meal_code in ("ebed", "vacsora") and days_per_meal > 1 and covered_days > 1:
                        prev = batch_state.get(meal_code)
                        if prev and prev[0] == title_key and prev[1] == day_idx - 1 and prev[2] > 0:
                            batch_state[meal_code] = (title_key, day_idx, prev[2] - 1)
                            continue
                        batch_state[meal_code] = (title_key, day_idx, covered_days - 1)
                        qty_scale = 1.0
                    else:
                        batch_state.pop(meal_code, None)
                        qty_scale = round(household_size / servings, 2) if rec_obj else 1.0

                    origin_label = f"{day_label} {meal_code}: {slot.get('title', '')}"
                    custom_ings = slot.get("custom_ingredients") or []
                    if rec_obj and not custom_ings:
                        for ing in rec_obj["ingredients"]:
                            _accumulate(
                                ing["name"],
                                round(float(ing["quantity"]) * qty_scale, 2),
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
            item
            for item in self.list_general_items(include_ordered=False, user_id=user_id)
            if item["status"] == "PENDING"
        ]
        in_cart_general = [
            item
            for item in self.list_general_items(include_ordered=False, user_id=user_id)
            if item["status"] == "IN_CART"
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
    # Chat napló
    # -------------------------------------------------------------------------
    def add_chat_message(
        self, role: str, content: str, source: str = "web", user_id: int = 1
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO chat_messages (user_id, role, source, content) VALUES (?, ?, ?, ?)",
                (int(user_id), role, source, content),
            )

    def get_recent_chat_messages(self, limit: int = 16, user_id: int = 1) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, role, source, content, created_at FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (int(user_id), limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def clear_chat_history(self, user_id: int = 1) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (int(user_id),))

    # -------------------------------------------------------------------------
    # Tervező preferenciák
    # -------------------------------------------------------------------------
    def get_planner_settings(self, user_id: int = 1) -> dict[str, Any]:
        result = dict(self.DEFAULT_PLANNER_SETTINGS)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM planner_settings WHERE user_id = ?",
                (int(user_id),),
            ).fetchall()
            for r in rows:
                if r["key"] in result:
                    try:
                        result[r["key"]] = json.loads(r["value_json"])
                    except Exception:
                        pass
        return result

    def update_planner_settings(
        self, updates: dict[str, Any], user_id: int = 1
    ) -> dict[str, Any]:
        current = self.get_planner_settings(user_id=user_id)
        with self.connect() as conn:
            for k, v in updates.items():
                if k not in self.DEFAULT_PLANNER_SETTINGS or v is None:
                    continue
                if k == "weekly_budget_ft":
                    v = max(0, int(v))
                elif k == "household_size":
                    v = max(1, min(12, int(v)))
                elif k == "plan_days":
                    v = max(1, min(7, int(v)))
                elif k == "days_per_meal":
                    v = max(1, min(4, int(v)))
                elif k == "min_healthy_score":
                    v = max(1.0, min(5.0, round(float(v), 1)))
                elif k == "ai_recommendation_count":
                    v = max(1, min(7, int(v)))
                elif k in (
                    "prefer_private_label",
                    "prefer_discounts_and_save_food",
                    "ai_recommendations_enabled",
                ):
                    v = bool(v)
                elif k == "allergens":
                    v = [str(a).strip().lower() for a in v if str(a).strip()]
                elif k == "ai_recommendation_meals":
                    cleaned = [
                        strip_accents(str(m).strip().lower())
                        for m in v
                        if strip_accents(str(m).strip().lower()) in MEAL_TYPES
                    ]
                    v = cleaned or ["ebed"]
                current[k] = v
                conn.execute(
                    """
                    INSERT INTO planner_settings (user_id, key, value_json, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(user_id, key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = datetime('now')
                    """,
                    (int(user_id), k, json.dumps(v, ensure_ascii=False)),
                )
        return current

    # -------------------------------------------------------------------------
    # Páros Kaja Tinder Match
    # -------------------------------------------------------------------------
    def create_tinder_session(
        self,
        meal_type: str = "ebed",
        target_days: list[str] | None = None,
        owner_user_id: int = 1,
    ) -> dict[str, Any]:
        meal_norm = strip_accents(meal_type.lower().strip())
        if meal_norm not in MEAL_TYPES:
            meal_norm = "ebed"
        days = target_days or ["hetfo", "kedd"]
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(4))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tinder_sessions (code, owner_user_id, meal_type, target_days_json)
                VALUES (?, ?, ?, ?)
                """,
                (code, int(owner_user_id), meal_norm, json.dumps(days, ensure_ascii=False)),
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

        owner_uid = int(sess["owner_user_id"])
        meal_type = str(sess["meal_type"] or "ebed")
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

        owner_recipes = self.list_recipes(user_id=owner_uid)
        deck_recipes = [r for r in owner_recipes if meal_type in r["categories"]]
        if not deck_recipes:
            deck_recipes = owner_recipes

        matched_ids = sorted(p1_likes.intersection(p2_likes))
        recipes_by_id = {r["id"]: r for r in owner_recipes}
        matched_recipes = [recipes_by_id[rid] for rid in matched_ids if rid in recipes_by_id]

        return {
            "code": sess["code"],
            "owner_user_id": owner_uid,
            "meal_type": meal_type,
            "target_days": json.loads(sess["target_days_json"]),
            "created_at": sess["created_at"],
            "p1_swiped_ids": p1_swiped,
            "p2_swiped_ids": p2_swiped,
            "p1_like_count": len(p1_likes),
            "p2_like_count": len(p2_likes),
            "deck_recipes": deck_recipes,
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
