"""Хранилище на SQLite.

Один товар проверяется один раз, даже если его отслеживают сто человек: products общие,
а настройки уведомлений — в subscriptions. В истории храним только изменения
(цена, цена по карте, наличие), поэтому база не растёт от каждой проверки.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from .models import Marketplace, PricePoint, Product, ProductRef, Snapshot, Subscription

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    marketplace TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    image_url TEXT,
    price INTEGER,
    old_price INTEGER,
    card_price INTEGER,
    in_stock INTEGER NOT NULL DEFAULT 0,
    stock_qty INTEGER,
    min_price INTEGER,
    max_price INTEGER,
    first_price INTEGER,
    checked_at TEXT,
    next_check_at TEXT NOT NULL,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (marketplace, external_id)
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    drop_percent REAL NOT NULL DEFAULT 0,
    target_price INTEGER,
    any_change INTEGER NOT NULL DEFAULT 0,
    notify_stock INTEGER NOT NULL DEFAULT 1,
    baseline_price INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, product_id)
);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    ts TEXT NOT NULL,
    price INTEGER,
    old_price INTEGER,
    card_price INTEGER,
    in_stock INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_history_product ON price_history (product_id, ts);
CREATE INDEX IF NOT EXISTS ix_products_due ON products (next_check_at);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds") if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _product(row: aiosqlite.Row) -> Product:
    return Product(
        id=row["id"], marketplace=Marketplace(row["marketplace"]), external_id=row["external_id"], url=row["url"],
        title=row["title"], image_url=row["image_url"], price=row["price"], old_price=row["old_price"],
        card_price=row["card_price"], in_stock=bool(row["in_stock"]), stock_qty=row["stock_qty"],
        min_price=row["min_price"], max_price=row["max_price"], first_price=row["first_price"],
        checked_at=_dt(row["checked_at"]), fail_count=row["fail_count"], last_error=row["last_error"],
    )


def _subscription(row: aiosqlite.Row) -> Subscription:
    return Subscription(
        id=row["id"], user_id=row["user_id"], product_id=row["product_id"], drop_percent=row["drop_percent"],
        target_price=row["target_price"], any_change=bool(row["any_change"]), notify_stock=bool(row["notify_stock"]),
        baseline_price=row["baseline_price"], created_at=_dt(row["created_at"]),
    )


@dataclass(frozen=True)
class Stats:
    users: int
    active_users: int
    products: int
    subscriptions: int
    by_marketplace: dict[str, int]
    failing: int


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> "Database":
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        return self

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database.connect() не вызван"
        return self._db

    # --- пользователи ---------------------------------------------------------
    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self.db.execute(
            "INSERT INTO users (id, username, first_name, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, active=1",
            (user_id, username, first_name, _ts(utcnow())),
        )
        await self.db.commit()

    async def deactivate_user(self, user_id: int) -> None:
        """Пользователь заблокировал бота — перестаём проверять его товары."""
        await self.db.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
        await self.db.commit()

    # --- товары ---------------------------------------------------------------
    async def get_product(self, product_id: int) -> Product | None:
        async with self.db.execute("SELECT * FROM products WHERE id=?", (product_id,)) as cur:
            row = await cur.fetchone()
        return _product(row) if row else None

    async def find_product(self, ref: ProductRef) -> Product | None:
        async with self.db.execute("SELECT * FROM products WHERE marketplace=? AND external_id=?",
                                   (ref.marketplace.value, ref.external_id)) as cur:
            row = await cur.fetchone()
        return _product(row) if row else None

    async def add_product(self, ref: ProductRef, snap: Snapshot, now: datetime, next_check: datetime) -> Product:
        """Создаёт товар по первой проверке (или возвращает существующий, обновив его)."""
        existing = await self.find_product(ref)
        if existing is not None:
            await self.save_check(existing.id, snap, now, next_check)
            return await self.get_product(existing.id)
        cur = await self.db.execute(
            "INSERT INTO products (marketplace, external_id, url, title, image_url, next_check_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ref.marketplace.value, ref.external_id, ref.url, snap.title, snap.image_url, _ts(next_check), _ts(now)),
        )
        product_id = cur.lastrowid
        await self.save_check(product_id, snap, now, next_check)
        return await self.get_product(product_id)

    async def save_check(self, product_id: int, snap: Snapshot, now: datetime, next_check: datetime) -> None:
        async with self.db.execute(
            "SELECT price, card_price, in_stock FROM price_history WHERE product_id=? ORDER BY id DESC LIMIT 1",
            (product_id,),
        ) as cur:
            last = await cur.fetchone()
        changed = last is None or (last["price"], last["card_price"], bool(last["in_stock"])) != (
            snap.price, snap.card_price, snap.in_stock)
        if changed:
            await self.db.execute(
                "INSERT INTO price_history (product_id, ts, price, old_price, card_price, in_stock) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (product_id, _ts(now), snap.price, snap.old_price, snap.card_price, int(snap.in_stock)),
            )
        await self.db.execute(
            """UPDATE products SET title=?, image_url=COALESCE(?, image_url),
                   price=COALESCE(?, price), old_price=?, card_price=?, in_stock=?, stock_qty=?,
                   min_price=CASE WHEN ? IS NULL THEN min_price ELSE MIN(COALESCE(min_price, ?), ?) END,
                   max_price=CASE WHEN ? IS NULL THEN max_price ELSE MAX(COALESCE(max_price, ?), ?) END,
                   first_price=COALESCE(first_price, ?),
                   checked_at=?, next_check_at=?, fail_count=0, last_error=NULL
               WHERE id=?""",
            (snap.title, snap.image_url, snap.price, snap.old_price, snap.card_price, int(snap.in_stock),
             snap.stock_qty, snap.price, snap.price, snap.price, snap.price, snap.price, snap.price, snap.price,
             _ts(now), _ts(next_check), product_id),
        )
        await self.db.commit()

    async def save_error(self, product_id: int, error: str, next_check: datetime) -> int:
        await self.db.execute(
            "UPDATE products SET fail_count=fail_count+1, last_error=?, next_check_at=? WHERE id=?",
            (error[:300], _ts(next_check), product_id),
        )
        await self.db.commit()
        async with self.db.execute("SELECT fail_count FROM products WHERE id=?", (product_id,)) as cur:
            return (await cur.fetchone())["fail_count"]

    async def due_products(self, now: datetime, limit: int = 300) -> list[Product]:
        """Товары, которые пора проверить и которые кто-то отслеживает."""
        async with self.db.execute(
            """SELECT p.* FROM products p
               WHERE p.next_check_at <= ? AND EXISTS (
                   SELECT 1 FROM subscriptions s JOIN users u ON u.id = s.user_id
                   WHERE s.product_id = p.id AND u.active = 1)
               ORDER BY p.next_check_at LIMIT ?""",
            (_ts(now), limit),
        ) as cur:
            return [_product(r) for r in await cur.fetchall()]

    async def history(self, product_id: int) -> list[PricePoint]:
        async with self.db.execute(
            "SELECT ts, price, card_price, in_stock FROM price_history WHERE product_id=? ORDER BY ts, id",
            (product_id,),
        ) as cur:
            return [PricePoint(_dt(r["ts"]), r["price"], r["card_price"], bool(r["in_stock"]))
                    for r in await cur.fetchall()]

    # --- подписки -------------------------------------------------------------
    async def subscribe(self, user_id: int, product_id: int, baseline: int | None) -> Subscription:
        await self.db.execute(
            "INSERT OR IGNORE INTO subscriptions (user_id, product_id, baseline_price, created_at) VALUES (?, ?, ?, ?)",
            (user_id, product_id, baseline, _ts(utcnow())),
        )
        await self.db.commit()
        return await self.get_subscription(user_id, product_id)

    async def get_subscription(self, user_id: int, product_id: int) -> Subscription | None:
        async with self.db.execute("SELECT * FROM subscriptions WHERE user_id=? AND product_id=?",
                                   (user_id, product_id)) as cur:
            row = await cur.fetchone()
        return _subscription(row) if row else None

    async def update_subscription(self, sub_id: int, **fields) -> None:
        allowed = {"drop_percent", "target_price", "any_change", "notify_stock", "baseline_price"}
        if not fields or not set(fields) <= allowed:
            raise ValueError(f"нельзя обновить поля {set(fields) - allowed}")
        sets = ", ".join(f"{k}=?" for k in fields)
        values = [int(v) if isinstance(v, bool) else v for v in fields.values()]
        await self.db.execute(f"UPDATE subscriptions SET {sets} WHERE id=?", (*values, sub_id))
        await self.db.commit()

    async def unsubscribe(self, user_id: int, product_id: int) -> None:
        await self.db.execute("DELETE FROM subscriptions WHERE user_id=? AND product_id=?", (user_id, product_id))
        await self.db.commit()

    async def subscribers(self, product_id: int) -> list[Subscription]:
        async with self.db.execute(
            "SELECT s.* FROM subscriptions s JOIN users u ON u.id = s.user_id WHERE s.product_id=? AND u.active=1",
            (product_id,),
        ) as cur:
            return [_subscription(r) for r in await cur.fetchall()]

    async def user_products(self, user_id: int) -> list[tuple[Product, Subscription]]:
        async with self.db.execute(
            "SELECT p.*, s.id AS sid FROM subscriptions s JOIN products p ON p.id = s.product_id "
            "WHERE s.user_id=? ORDER BY s.id",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
        async with self.db.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)) as cur:
            subs = {r["id"]: _subscription(r) for r in await cur.fetchall()}
        return [(_product(r), subs[r["sid"]]) for r in rows]

    async def count_user_products(self, user_id: int) -> int:
        async with self.db.execute("SELECT COUNT(*) AS n FROM subscriptions WHERE user_id=?", (user_id,)) as cur:
            return (await cur.fetchone())["n"]

    async def stats(self) -> Stats:
        async def scalar(sql: str) -> int:
            async with self.db.execute(sql) as cur:
                return (await cur.fetchone())[0]

        async with self.db.execute(
            "SELECT marketplace, COUNT(*) FROM products p WHERE EXISTS "
            "(SELECT 1 FROM subscriptions s WHERE s.product_id=p.id) GROUP BY marketplace"
        ) as cur:
            by_mp = {r[0]: r[1] for r in await cur.fetchall()}
        return Stats(
            users=await scalar("SELECT COUNT(*) FROM users"),
            active_users=await scalar("SELECT COUNT(DISTINCT user_id) FROM subscriptions"),
            products=sum(by_mp.values()),
            subscriptions=await scalar("SELECT COUNT(*) FROM subscriptions"),
            by_marketplace=by_mp,
            failing=await scalar("SELECT COUNT(*) FROM products WHERE fail_count >= 3"),
        )
