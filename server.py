from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", str(BASE_DIR / "data"))).resolve()
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "fly_tying.db"))).resolve()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
HOST = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "fly-tying-dev-secret").encode("utf-8")
SESSION_COOKIE = "flytying_session"
GUEST_USER_EMAIL = "guest@local"
USING_POSTGRES = DATABASE_URL.startswith("postgres")


LOCATION_SEED = [
    {
        "name": "Drawer A1",
        "location_type": "Drawer",
        "zone": "Main bench",
        "description": "Top drawer beside the vise for hooks, beads, and frequently used metal parts.",
    },
    {
        "name": "Feather Bin",
        "location_type": "Bin",
        "zone": "Closet shelf",
        "description": "Clear bin for saddles, capes, marabou packs, and larger feather patches.",
    },
    {
        "name": "Travel Kit",
        "location_type": "Travel Kit",
        "zone": "Go bag",
        "description": "Portable pouch for trip-ready thread, hooks, and emergency refills.",
    },
]

MATERIAL_SEED = [
    {
        "name": "Whiting Saddle Hackle",
        "category": "Hackle",
        "brand": "Whiting",
        "variant": "Grizzly",
        "quantity": 2,
        "location_name": "Feather Bin",
        "notes": "Strong dry fly option for sizes 12-16.",
    },
    {
        "name": "Slotted Tungsten Beads",
        "category": "Beads",
        "brand": "Firehole",
        "variant": "Black nickel 3.3 mm",
        "quantity": 12,
        "location_name": "Drawer A1",
        "notes": "Keep beside jig hooks and lead-free wire.",
    },
    {
        "name": "UTC Ultra Thread",
        "category": "Thread",
        "brand": "UTC",
        "variant": "70 Denier Olive",
        "quantity": 1,
        "location_name": "Travel Kit",
        "notes": "Backup spool for nymph patterns.",
    },
]

FLY_SEED = [
    {
        "name": "Pheasant Tail Nymph",
        "style": "Nymph",
        "hook_size": "Size 14",
        "recipe": "Tail of pheasant tail fibers, slim abdomen, fine rib, thorax, bead head, finish with dark thread.",
        "notes": "Classic searching nymph for trout water.",
        "material_names": ["UTC Ultra Thread", "Slotted Tungsten Beads"],
    }
]


def normalize_query(query: str) -> str:
    if not USING_POSTGRES:
        return query

    normalized = query.replace("?", "%s")
    normalized = normalized.replace(" COLLATE NOCASE", "")
    normalized = normalized.replace("datetime(created_at)", "created_at")
    normalized = re.sub(r"\bLIKE\b", "ILIKE", normalized)
    return normalized


def connect_db() -> Any:
    if USING_POSTGRES:
        if psycopg is None or dict_row is None:
            raise RuntimeError("DATABASE_URL is set, but psycopg is not installed.")
        return psycopg.connect(DATABASE_URL, row_factory=dict_row)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def db_execute(connection: Any, query: str, params: tuple[Any, ...] | list[Any] = ()) -> Any:
    return connection.execute(normalize_query(query), params)


def db_executemany(connection: Any, query: str, rows: list[dict[str, Any]] | list[tuple[Any, ...]]) -> Any:
    return connection.executemany(normalize_query(query), rows)


def db_row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row)


def db_scalar(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        if key in row:
            return row[key]
        return list(row.values())[index]
    return row[index]


def db_bool_sql(value: bool) -> str:
    return "TRUE" if value and USING_POSTGRES else "FALSE" if USING_POSTGRES else ("1" if value else "0")


def insert_and_get_id(connection: Any, query: str, params: tuple[Any, ...]) -> int:
    if USING_POSTGRES:
        returning_query = f"{query.strip().rstrip(';')} RETURNING id"
        row = db_execute(connection, returning_query, params).fetchone()
        return int(db_scalar(row, "id"))

    cursor = db_execute(connection, query, params)
    return int(cursor.lastrowid)


def make_session_signature(session_id: str) -> str:
    return hmac.new(SESSION_SECRET, session_id.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "picture": row["picture"],
        "is_guest": bool(row["is_guest"]),
    }


def initialize_database() -> None:
    if not USING_POSTGRES:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_db() as connection:
        if USING_POSTGRES:
            initialize_postgres_schema(connection)
        else:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_sub TEXT UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    picture TEXT DEFAULT '',
                    is_guest INTEGER NOT NULL DEFAULT 0 CHECK(is_guest IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    location_type TEXT NOT NULL DEFAULT 'Drawer',
                    zone TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    UNIQUE(user_id, name)
                );

                CREATE TABLE IF NOT EXISTS materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    brand TEXT DEFAULT '',
                    variant TEXT DEFAULT '',
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
                    is_out INTEGER NOT NULL DEFAULT 0 CHECK(is_out IN (0, 1)),
                    image_data TEXT DEFAULT '',
                    location_id INTEGER NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(location_id) REFERENCES locations(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS flies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    style TEXT DEFAULT '',
                    hook_size TEXT DEFAULT '',
                    recipe TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    image_data TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS fly_materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fly_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(fly_id) REFERENCES flies(id) ON DELETE CASCADE,
                    FOREIGN KEY(material_id) REFERENCES materials(id) ON DELETE CASCADE,
                    UNIQUE(fly_id, material_id)
                );

                CREATE TABLE IF NOT EXISTS bug_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    page TEXT DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'Medium',
                    details TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'Open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )

        ensure_column(connection, "locations", "location_type", "TEXT NOT NULL DEFAULT 'Drawer'")
        ensure_column(connection, "locations", "user_id", "INTEGER")
        ensure_column(connection, "materials", "user_id", "INTEGER")
        ensure_column(connection, "materials", "is_out", "INTEGER NOT NULL DEFAULT 0 CHECK(is_out IN (0, 1))")
        ensure_column(connection, "materials", "image_data", "TEXT DEFAULT ''")
        ensure_column(connection, "flies", "user_id", "INTEGER")
        ensure_column(connection, "flies", "style", "TEXT DEFAULT ''")
        ensure_column(connection, "flies", "hook_size", "TEXT DEFAULT ''")
        ensure_column(connection, "flies", "recipe", "TEXT DEFAULT ''")
        ensure_column(connection, "flies", "notes", "TEXT DEFAULT ''")
        ensure_column(connection, "flies", "image_data", "TEXT DEFAULT ''")
        ensure_column(connection, "bug_reports", "user_id", "INTEGER")
        ensure_column(connection, "bug_reports", "page", "TEXT DEFAULT ''")
        ensure_column(connection, "bug_reports", "severity", "TEXT NOT NULL DEFAULT 'Medium'")
        ensure_column(connection, "bug_reports", "details", "TEXT NOT NULL DEFAULT ''")
        ensure_column(connection, "bug_reports", "status", "TEXT NOT NULL DEFAULT 'Open'")

        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_materials_user_name ON materials(user_id, name)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_materials_user_category ON materials(user_id, category)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_materials_user_location ON materials(user_id, location_id)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_fly_user_name ON flies(user_id, name)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_fly_material_fly ON fly_materials(fly_id)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_bug_reports_user_created ON bug_reports(user_id, created_at DESC)")
        db_execute(connection, "CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)")

        guest_user_id = ensure_guest_user(connection)
        migrate_legacy_data(connection, guest_user_id)
        seed_guest_data_if_needed(connection, guest_user_id)


def initialize_postgres_schema(connection: Any) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            google_sub TEXT UNIQUE,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            picture TEXT DEFAULT '',
            is_guest BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id BIGSERIAL PRIMARY KEY,
            session_id TEXT NOT NULL UNIQUE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS locations (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            location_type TEXT NOT NULL DEFAULT 'Drawer',
            zone TEXT DEFAULT '',
            description TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS materials (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT DEFAULT '',
            variant TEXT DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
            is_out BOOLEAN NOT NULL DEFAULT FALSE,
            image_data TEXT DEFAULT '',
            location_id BIGINT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
            notes TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS flies (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            style TEXT DEFAULT '',
            hook_size TEXT DEFAULT '',
            recipe TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            image_data TEXT DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS fly_materials (
            id BIGSERIAL PRIMARY KEY,
            fly_id BIGINT NOT NULL REFERENCES flies(id) ON DELETE CASCADE,
            material_id BIGINT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(fly_id, material_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bug_reports (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            page TEXT DEFAULT '',
            severity TEXT NOT NULL DEFAULT 'Medium',
            details TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for statement in statements:
        db_execute(connection, statement)


def ensure_column(connection: Any, table: str, column: str, definition: str) -> None:
    if USING_POSTGRES:
        db_execute(connection, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        return

    columns = {
        row["name"]
        for row in db_execute(connection, f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        db_execute(connection, f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_guest_user(connection: sqlite3.Connection) -> int:
    row = db_execute(
        connection,
        "SELECT id FROM users WHERE email = ?",
        (GUEST_USER_EMAIL,),
    ).fetchone()
    if row:
        return int(db_scalar(row, "id"))

    return insert_and_get_id(
        connection,
        """
        INSERT INTO users (google_sub, email, name, picture, is_guest)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("guest-local", GUEST_USER_EMAIL, "Guest", "", True if USING_POSTGRES else 1),
    )


def migrate_legacy_data(connection: sqlite3.Connection, guest_user_id: int) -> None:
    db_execute(connection, "UPDATE locations SET user_id = ? WHERE user_id IS NULL", (guest_user_id,))
    db_execute(connection, "UPDATE materials SET user_id = ? WHERE user_id IS NULL", (guest_user_id,))
    db_execute(connection, "UPDATE flies SET user_id = ? WHERE user_id IS NULL", (guest_user_id,))
    db_execute(
        connection,
        """
        UPDATE locations
        SET location_type = CASE
            WHEN lower(name) LIKE '%bin%' THEN 'Bin'
            WHEN lower(name) LIKE '%travel kit%' THEN 'Travel Kit'
            ELSE coalesce(location_type, 'Drawer')
        END
        WHERE location_type IS NULL OR location_type = ''
        """
    )
    connection.commit()


def seed_guest_data_if_needed(connection: sqlite3.Connection, guest_user_id: int) -> None:
    location_count = db_scalar(
        db_execute(
            connection,
        "SELECT COUNT(*) FROM locations WHERE user_id = ?",
        (guest_user_id,),
    ).fetchone(), "count", 0)
    if location_count == 0:
        db_executemany(
            connection,
            """
            INSERT INTO locations (user_id, name, location_type, zone, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    guest_user_id,
                    location["name"],
                    location["location_type"],
                    location["zone"],
                    location["description"],
                )
                for location in LOCATION_SEED
            ],
        )

    material_count = db_scalar(
        db_execute(
            connection,
        "SELECT COUNT(*) FROM materials WHERE user_id = ?",
        (guest_user_id,),
    ).fetchone(), "count", 0)
    if material_count == 0:
        location_lookup = {
            row["name"]: row["id"]
            for row in db_execute(
                connection,
                "SELECT id, name FROM locations WHERE user_id = ?",
                (guest_user_id,),
            ).fetchall()
        }
        material_rows = [
            (
                guest_user_id,
                item["name"],
                item["category"],
                item["brand"],
                item["variant"],
                item["quantity"],
                location_lookup[item["location_name"]],
                item["notes"],
            )
            for item in MATERIAL_SEED
        ]
        db_executemany(
            connection,
            """
            INSERT INTO materials (user_id, name, category, brand, variant, quantity, location_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            material_rows,
        )

    fly_count = db_scalar(
        db_execute(
            connection,
        "SELECT COUNT(*) FROM flies WHERE user_id = ?",
        (guest_user_id,),
    ).fetchone(), "count", 0)
    if fly_count == 0:
        material_lookup = {
            row["name"]: row["id"]
            for row in db_execute(
                connection,
                "SELECT id, name FROM materials WHERE user_id = ?",
                (guest_user_id,),
            ).fetchall()
        }
        for fly in FLY_SEED:
            fly_id = insert_and_get_id(
                connection,
                """
                INSERT INTO flies (user_id, name, style, hook_size, recipe, notes, image_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guest_user_id,
                    fly["name"],
                    fly["style"],
                    fly["hook_size"],
                    fly["recipe"],
                    fly["notes"],
                    "",
                ),
            )
            for material_name in fly["material_names"]:
                material_id = material_lookup.get(material_name)
                if material_id:
                    db_execute(
                        connection,
                        "INSERT INTO fly_materials (fly_id, material_id) VALUES (?, ?)",
                        (fly_id, material_id),
                    )
    connection.commit()


def copy_guest_seed_to_user(connection: sqlite3.Connection, user_id: int) -> None:
    guest_user_id = db_scalar(db_execute(
        connection,
        "SELECT id FROM users WHERE email = ?",
        (GUEST_USER_EMAIL,),
    ).fetchone(), "id")

    location_count = db_scalar(db_execute(
        connection,
        "SELECT COUNT(*) FROM locations WHERE user_id = ?",
        (user_id,),
    ).fetchone(), "count", 0)
    if location_count > 0:
        return

    guest_locations = db_execute(
        connection,
        """
        SELECT name, location_type, zone, description
        FROM locations
        WHERE user_id = ?
        ORDER BY id
        """,
        (guest_user_id,),
    ).fetchall()
    for row in guest_locations:
        db_execute(
            connection,
            """
            INSERT INTO locations (user_id, name, location_type, zone, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, row["name"], row["location_type"], row["zone"], row["description"]),
        )

    guest_lookup = {
        row["name"]: row["id"]
        for row in db_execute(
            connection,
            "SELECT id, name FROM locations WHERE user_id = ?",
            (guest_user_id,),
        ).fetchall()
    }
    new_lookup = {
        row["name"]: row["id"]
        for row in db_execute(
            connection,
            "SELECT id, name FROM locations WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }
    guest_materials = db_execute(
        connection,
        """
        SELECT name, category, brand, variant, quantity, is_out, image_data, location_id, notes
        FROM materials
        WHERE user_id = ?
        ORDER BY id
        """,
        (guest_user_id,),
    ).fetchall()
    for row in guest_materials:
        location_name = next(name for name, location_id in guest_lookup.items() if location_id == row["location_id"])
        db_execute(
            connection,
            """
            INSERT INTO materials (user_id, name, category, brand, variant, quantity, is_out, image_data, location_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                row["name"],
                row["category"],
                row["brand"],
                row["variant"],
                row["quantity"],
                row["is_out"],
                row["image_data"],
                new_lookup[location_name],
                row["notes"],
            ),
        )

    guest_material_lookup = {
        row["name"]: row["id"]
        for row in db_execute(
            connection,
            "SELECT id, name FROM materials WHERE user_id = ?",
            (guest_user_id,),
        ).fetchall()
    }
    new_material_lookup = {
        row["name"]: row["id"]
        for row in db_execute(
            connection,
            "SELECT id, name FROM materials WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    }
    guest_flies = db_execute(
        connection,
        """
        SELECT id, name, style, hook_size, recipe, notes, image_data
        FROM flies
        WHERE user_id = ?
        ORDER BY id
        """,
        (guest_user_id,),
    ).fetchall()
    for row in guest_flies:
        new_fly_id = insert_and_get_id(
            connection,
            """
            INSERT INTO flies (user_id, name, style, hook_size, recipe, notes, image_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                row["name"],
                row["style"],
                row["hook_size"],
                row["recipe"],
                row["notes"],
                row["image_data"],
            ),
        )
        guest_links = db_execute(
            connection,
            """
            SELECT materials.name
            FROM fly_materials
            JOIN materials ON materials.id = fly_materials.material_id
            WHERE fly_materials.fly_id = ?
            """,
            (row["id"],),
        ).fetchall()
        for link in guest_links:
            material_id = new_material_lookup.get(link["name"])
            if material_id:
                db_execute(
                    connection,
                    "INSERT INTO fly_materials (fly_id, material_id) VALUES (?, ?)",
                    (new_fly_id, material_id),
                )
    connection.commit()


def list_materials(user_id: int, filters: dict[str, str]) -> list[dict[str, Any]]:
    query = """
        SELECT
            materials.id,
            materials.name,
            materials.category,
            materials.brand,
            materials.variant,
            materials.quantity,
            materials.is_out,
            materials.image_data,
            materials.notes,
            locations.id AS location_id,
            locations.name AS location_name,
            locations.location_type AS location_type,
            locations.zone AS location_zone
        FROM materials
        JOIN locations ON locations.id = materials.location_id
        WHERE materials.user_id = ?
    """
    params: list[Any] = [user_id]

    search_value = filters.get("search", "").strip()
    if search_value:
        query += """
            AND (
                materials.name LIKE ?
                OR materials.category LIKE ?
                OR materials.brand LIKE ?
                OR materials.variant LIKE ?
                OR materials.notes LIKE ?
                OR locations.name LIKE ?
                OR locations.zone LIKE ?
            )
        """
        like_value = f"%{search_value}%"
        params.extend([like_value] * 7)

    category_value = filters.get("category", "").strip()
    if category_value:
        query += " AND materials.category = ?"
        params.append(category_value)

    location_value = filters.get("location_id", "").strip()
    if location_value:
        query += " AND materials.location_id = ?"
        params.append(int(location_value))

    location_type_value = filters.get("location_type", "").strip()
    if location_type_value:
        query += " AND locations.location_type = ?"
        params.append(location_type_value)

    status_value = filters.get("status", "").strip().lower()
    if status_value == "out":
        query += f" AND materials.is_out = {db_bool_sql(True)}"
    elif status_value == "in":
        query += f" AND materials.is_out = {db_bool_sql(False)}"

    query += " ORDER BY lower(materials.name) ASC"

    with connect_db() as connection:
        rows = db_execute(connection, query, params).fetchall()
        return [db_row_to_dict(row) for row in rows]


def list_flies(user_id: int) -> list[dict[str, Any]]:
    with connect_db() as connection:
        fly_rows = db_execute(
            connection,
            """
            SELECT id, name, style, hook_size, recipe, notes, image_data
            FROM flies
            WHERE user_id = ?
            ORDER BY lower(name) ASC
            """,
            (user_id,),
        ).fetchall()

        material_rows = db_execute(
            connection,
            """
            SELECT
                fly_materials.fly_id,
                materials.id,
                materials.name,
                materials.category,
                materials.brand,
                materials.variant,
                materials.quantity,
                materials.is_out,
                locations.name AS location_name,
                locations.location_type AS location_type,
                locations.zone AS location_zone
            FROM fly_materials
            JOIN flies ON flies.id = fly_materials.fly_id
            JOIN materials ON materials.id = fly_materials.material_id
            LEFT JOIN locations ON locations.id = materials.location_id
            WHERE flies.user_id = ?
            ORDER BY lower(materials.name) ASC
            """,
            (user_id,),
        ).fetchall()

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in material_rows:
        grouped.setdefault(row["fly_id"], []).append(
            {
                "id": row["id"],
                "name": row["name"],
                "category": row["category"],
                "brand": row["brand"],
                "variant": row["variant"],
                "quantity": row["quantity"],
                "is_out": row["is_out"],
                "location_name": row["location_name"],
                "location_type": row["location_type"],
                "location_zone": row["location_zone"],
            }
        )

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "style": row["style"],
            "hook_size": row["hook_size"],
            "recipe": row["recipe"],
            "notes": row["notes"],
            "image_data": row["image_data"],
            "materials": grouped.get(row["id"], []),
        }
        for row in fly_rows
    ]


def get_summary(user_id: int) -> dict[str, int]:
    with connect_db() as connection:
        total_materials = db_scalar(db_execute(
            connection,
            "SELECT COUNT(*) FROM materials WHERE user_id = ?",
            (user_id,),
        ).fetchone(), "count", 0)
        total_locations = db_scalar(db_execute(
            connection,
            "SELECT COUNT(*) FROM locations WHERE user_id = ?",
            (user_id,),
        ).fetchone(), "count", 0)
        out_count = db_scalar(db_execute(
            connection,
            f"SELECT COUNT(*) FROM materials WHERE user_id = ? AND is_out = {db_bool_sql(True)}",
            (user_id,),
        ).fetchone(), "count", 0)
        fly_count = db_scalar(db_execute(
            connection,
            "SELECT COUNT(*) FROM flies WHERE user_id = ?",
            (user_id,),
        ).fetchone(), "count", 0)
        return {
            "material_count": total_materials,
            "location_count": total_locations,
            "out_count": out_count,
            "fly_count": fly_count,
        }


def list_bug_reports(user_id: int) -> list[dict[str, Any]]:
    with connect_db() as connection:
        rows = db_execute(
            connection,
            """
            SELECT id, title, page, severity, details, status, created_at
            FROM bug_reports
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        return [db_row_to_dict(row) for row in rows]


def list_locations(user_id: int) -> list[dict[str, Any]]:
    query = """
        SELECT
            locations.id,
            locations.name,
            locations.location_type,
            locations.zone,
            locations.description,
            COUNT(materials.id) AS material_count
        FROM locations
        LEFT JOIN materials ON materials.location_id = locations.id
        WHERE locations.user_id = ?
        GROUP BY locations.id
        ORDER BY lower(locations.name) ASC
    """

    with connect_db() as connection:
        rows = db_execute(connection, query, (user_id,)).fetchall()
        return [db_row_to_dict(row) for row in rows]


def create_location(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    location_type = str(payload.get("location_type", "")).strip() or "Drawer"
    zone = str(payload.get("zone", "")).strip()
    description = str(payload.get("description", "")).strip()
    valid_types = {"Drawer", "Bin", "Travel Kit"}

    if not name:
        raise ValueError("Location name is required.")
    if location_type not in valid_types:
        raise ValueError("Storage type must be Drawer, Bin, or Travel Kit.")

    with connect_db() as connection:
        location_id = insert_and_get_id(
            connection,
            """
            INSERT INTO locations (user_id, name, location_type, zone, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, name, location_type, zone, description),
        )
        connection.commit()
        row = db_execute(
            connection,
            """
            SELECT id, name, location_type, zone, description, 0 AS material_count
            FROM locations
            WHERE id = ?
            """,
            (location_id,),
        ).fetchone()
        return db_row_to_dict(row)


def create_material(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    category = str(payload.get("category", "")).strip()
    brand = str(payload.get("brand", "")).strip()
    variant = str(payload.get("variant", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    image_data = str(payload.get("image_data", "")).strip()
    location_id = str(payload.get("location_id", "")).strip()

    try:
        quantity = int(payload.get("quantity", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Quantity must be a whole number.") from exc

    if not name:
        raise ValueError("Material name is required.")
    if not category:
        raise ValueError("Category is required.")
    if quantity < 0:
        raise ValueError("Quantity cannot be negative.")
    if not location_id:
        raise ValueError("A storage location is required.")

    with connect_db() as connection:
        location_exists = db_execute(
            connection,
            "SELECT 1 FROM locations WHERE id = ? AND user_id = ?",
            (int(location_id), user_id),
        ).fetchone()
        if not location_exists:
            raise ValueError("The selected location does not exist.")

        material_id = insert_and_get_id(
            connection,
            """
            INSERT INTO materials (user_id, name, category, brand, variant, quantity, image_data, location_id, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, category, brand, variant, quantity, image_data, int(location_id), notes),
        )
        connection.commit()
        row = db_execute(
            connection,
            """
            SELECT
                materials.id,
                materials.name,
                materials.category,
                materials.brand,
                materials.variant,
                materials.quantity,
                materials.is_out,
                materials.image_data,
                materials.notes,
                locations.id AS location_id,
                locations.name AS location_name,
                locations.location_type AS location_type,
                locations.zone AS location_zone
            FROM materials
            JOIN locations ON locations.id = materials.location_id
            WHERE materials.id = ?
            """,
            (material_id,),
        ).fetchone()
        return db_row_to_dict(row)


def create_fly(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    style = str(payload.get("style", "")).strip()
    hook_size = str(payload.get("hook_size", "")).strip()
    recipe = str(payload.get("recipe", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    image_data = str(payload.get("image_data", "")).strip()
    material_ids = payload.get("material_ids", [])

    if not name:
        raise ValueError("Fly name is required.")
    if not isinstance(material_ids, list):
        raise ValueError("Fly materials must be sent as a list.")

    normalized_material_ids: list[int] = []
    for material_id in material_ids:
        try:
            normalized_material_ids.append(int(material_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("Each linked material must be valid.") from exc

    with connect_db() as connection:
        if normalized_material_ids:
            placeholders = ",".join("?" for _ in normalized_material_ids)
            valid_count = db_scalar(db_execute(
                connection,
                f"SELECT COUNT(*) FROM materials WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *normalized_material_ids),
            ).fetchone(), "count", 0)
            if valid_count != len(set(normalized_material_ids)):
                raise ValueError("One or more selected materials do not exist for this account.")

        fly_id = insert_and_get_id(
            connection,
            """
            INSERT INTO flies (user_id, name, style, hook_size, recipe, notes, image_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, name, style, hook_size, recipe, notes, image_data),
        )
        for material_id in sorted(set(normalized_material_ids)):
            db_execute(
                connection,
                "INSERT INTO fly_materials (fly_id, material_id) VALUES (?, ?)",
                (fly_id, material_id),
            )
        connection.commit()

    return get_fly_by_id(user_id, fly_id)


def create_bug_report(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title", "")).strip()
    page = str(payload.get("page", "")).strip()
    severity = str(payload.get("severity", "")).strip() or "Medium"
    details = str(payload.get("details", "")).strip()
    valid_severities = {"Low", "Medium", "High"}

    if not title:
        raise ValueError("Bug report title is required.")
    if not details:
        raise ValueError("Bug report details are required.")
    if severity not in valid_severities:
        raise ValueError("Severity must be Low, Medium, or High.")

    with connect_db() as connection:
        bug_report_id = insert_and_get_id(
            connection,
            """
            INSERT INTO bug_reports (user_id, title, page, severity, details, status)
            VALUES (?, ?, ?, ?, ?, 'Open')
            """,
            (user_id, title, page, severity, details),
        )
        connection.commit()
        row = db_execute(
            connection,
            """
            SELECT id, title, page, severity, details, status, created_at
            FROM bug_reports
            WHERE id = ?
            """,
            (bug_report_id,),
        ).fetchone()
        return db_row_to_dict(row)


def get_fly_by_id(user_id: int, fly_id: int) -> dict[str, Any]:
    flies = [fly for fly in list_flies(user_id) if fly["id"] == fly_id]
    if not flies:
        raise ValueError("That fly recipe could not be found.")
    return flies[0]


def update_material_status(user_id: int, material_id: int, is_out: bool) -> dict[str, Any]:
    with connect_db() as connection:
        cursor = db_execute(
            connection,
            "UPDATE materials SET is_out = ? WHERE id = ? AND user_id = ?",
            ((True if is_out else False) if USING_POSTGRES else (1 if is_out else 0), material_id, user_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("That material could not be found.")
        connection.commit()
        row = db_execute(
            connection,
            """
            SELECT
                materials.id,
                materials.name,
                materials.category,
                materials.brand,
                materials.variant,
                materials.quantity,
                materials.is_out,
                materials.image_data,
                materials.notes,
                locations.id AS location_id,
                locations.name AS location_name,
                locations.location_type AS location_type,
                locations.zone AS location_zone
            FROM materials
            JOIN locations ON locations.id = materials.location_id
            WHERE materials.id = ?
            """,
            (material_id,),
        ).fetchone()
        return db_row_to_dict(row)


def fetch_google_profile(credential: str) -> dict[str, Any]:
    if not GOOGLE_CLIENT_ID:
        raise ValueError("Google sign-in is not configured on this server yet.")

    encoded = urllib.parse.urlencode({"id_token": credential}).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/tokeninfo",
        data=encoded,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ValueError("Google sign-in could not be verified right now.") from exc

    if payload.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("This Google credential does not match the configured app.")
    if payload.get("email_verified") not in {"true", True}:
        raise ValueError("Your Google email must be verified before signing in.")

    return {
        "google_sub": payload["sub"],
        "email": payload["email"],
        "name": payload.get("name") or payload["email"].split("@")[0],
        "picture": payload.get("picture", ""),
    }


def create_or_update_google_user(profile: dict[str, Any]) -> dict[str, Any]:
    with connect_db() as connection:
        existing = db_execute(
            connection,
            "SELECT * FROM users WHERE google_sub = ? OR email = ?",
            (profile["google_sub"], profile["email"]),
        ).fetchone()
        if existing:
            db_execute(
                connection,
                """
                UPDATE users
                SET google_sub = ?, email = ?, name = ?, picture = ?, is_guest = ?
                WHERE id = ?
                """,
                (
                    profile["google_sub"],
                    profile["email"],
                    profile["name"],
                    profile["picture"],
                    False if USING_POSTGRES else 0,
                    existing["id"],
                ),
            )
            user_id = db_scalar(existing, "id")
        else:
            user_id = insert_and_get_id(
                connection,
                """
                INSERT INTO users (google_sub, email, name, picture, is_guest)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile["google_sub"],
                    profile["email"],
                    profile["name"],
                    profile["picture"],
                    False if USING_POSTGRES else 0,
                ),
            )

        copy_guest_seed_to_user(connection, user_id)
        connection.commit()
        row = db_execute(connection, "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return normalize_user(row)


def create_session(user_id: int) -> tuple[str, str]:
    session_id = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    with connect_db() as connection:
        db_execute(
            connection,
            "INSERT INTO sessions (session_id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user_id, expires_at),
        )
        connection.commit()
    return session_id, make_session_signature(session_id)


def delete_session(session_id: str) -> None:
    with connect_db() as connection:
        db_execute(connection, "DELETE FROM sessions WHERE session_id = ?", (session_id,))
        connection.commit()


def get_guest_user() -> dict[str, Any]:
    with connect_db() as connection:
        row = db_execute(
            connection,
            "SELECT * FROM users WHERE email = ?",
            (GUEST_USER_EMAIL,),
        ).fetchone()
        return normalize_user(row)


class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path == "/api/config":
                self.send_json(HTTPStatus.OK, self.build_config_payload())
                return

            if parsed.path == "/api/materials":
                filters = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                self.send_json(HTTPStatus.OK, list_materials(self.current_user["id"], filters))
                return

            if parsed.path == "/api/flies":
                self.send_json(HTTPStatus.OK, list_flies(self.current_user["id"]))
                return

            if parsed.path == "/api/summary":
                self.send_json(HTTPStatus.OK, get_summary(self.current_user["id"]))
                return

            if parsed.path == "/api/locations":
                self.send_json(HTTPStatus.OK, list_locations(self.current_user["id"]))
                return

            if parsed.path == "/api/bug-reports":
                self.send_json(HTTPStatus.OK, list_bug_reports(self.current_user["id"]))
                return

            self.serve_static(parsed.path)
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        try:
            payload = self.read_json_body()
            if parsed.path == "/api/materials":
                self.send_json(HTTPStatus.CREATED, create_material(self.current_user["id"], payload))
                return
            if parsed.path == "/api/flies":
                self.send_json(HTTPStatus.CREATED, create_fly(self.current_user["id"], payload))
                return
            if parsed.path == "/api/locations":
                self.send_json(HTTPStatus.CREATED, create_location(self.current_user["id"], payload))
                return
            if parsed.path == "/api/bug-reports":
                self.send_json(HTTPStatus.CREATED, create_bug_report(self.current_user["id"], payload))
                return
            if parsed.path == "/api/auth/google":
                profile = fetch_google_profile(str(payload.get("credential", "")).strip())
                user = create_or_update_google_user(profile)
                session_id, signature = create_session(user["id"])
                self.send_json(
                    HTTPStatus.OK,
                    {"user": user},
                    cookie_value=f"{session_id}.{signature}",
                )
                return
            if parsed.path == "/api/auth/logout":
                session_id = self.get_session_id_from_cookie()
                if session_id:
                    delete_session(session_id)
                self.send_json(HTTPStatus.OK, {"ok": True}, clear_cookie=True)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "The requested API route was not found.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except (sqlite3.IntegrityError, psycopg.IntegrityError if psycopg else sqlite3.IntegrityError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "That item already exists for this account.")
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)

        try:
            if parsed.path.startswith("/api/materials/") and parsed.path.endswith("/status"):
                material_id = int(parsed.path.split("/")[3])
                payload = self.read_json_body()
                if "is_out" not in payload:
                    raise ValueError("A material status value is required.")
                self.send_json(
                    HTTPStatus.OK,
                    update_material_status(self.current_user["id"], material_id, bool(payload["is_out"]))
                )
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "The requested API route was not found.")
        except ValueError as error:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.")

    def serve_static(self, requested_path: str) -> None:
        relative_path = requested_path.lstrip("/") or "index.html"
        file_path = (BASE_DIR / relative_path).resolve()
        if BASE_DIR not in file_path.parents and file_path != BASE_DIR:
            self.send_error_json(HTTPStatus.FORBIDDEN, "Access denied.")
            return

        if not file_path.exists() or not file_path.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "File not found.")
            return

        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        return json.loads(raw_body) if raw_body else {}

    def send_json(
        self,
        status: HTTPStatus,
        payload: Any,
        *,
        cookie_value: str | None = None,
        clear_cookie: bool = False,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie_value is not None:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={cookie_value}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000",
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json(status, {"error": message})

    def build_config_payload(self) -> dict[str, Any]:
        return {
            "google_client_id": GOOGLE_CLIENT_ID,
            "user": self.current_user,
        }

    @property
    def current_user(self) -> dict[str, Any]:
        if hasattr(self, "_current_user"):
            return self._current_user

        session_id = self.get_session_id_from_cookie()
        if session_id:
            with connect_db() as connection:
                row = db_execute(
                    connection,
                    """
                    SELECT users.*
                    FROM sessions
                    JOIN users ON users.id = sessions.user_id
                    WHERE sessions.session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if row:
                    self._current_user = normalize_user(row)
                    return self._current_user

        self._current_user = get_guest_user()
        return self._current_user

    def get_session_id_from_cookie(self) -> str | None:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(SESSION_COOKIE)
        if morsel is None:
            return None
        raw_value = morsel.value
        if "." not in raw_value:
            return None
        session_id, signature = raw_value.split(".", 1)
        expected_signature = make_session_signature(session_id)
        if not hmac.compare_digest(signature, expected_signature):
            return None
        return session_id

    def log_message(self, format: str, *args: Any) -> None:
        return


def run() -> None:
    initialize_database()
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Fly Tying Materials Tracker running on http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    run()
