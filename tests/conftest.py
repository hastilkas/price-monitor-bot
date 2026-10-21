from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from bot.db import Database
from bot.models import ProductRef, Snapshot
from bot.parsers import ParserError

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TZ = ZoneInfo("Europe/Moscow")
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)


def load_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def snap(price: int | None = 1000, in_stock: bool = True, **kw) -> Snapshot:
    return Snapshot(title=kw.pop("title", "Наушники"), price=price if in_stock else None, in_stock=in_stock, **kw)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


class FakeHub:
    """Подмена сети: цены задаются тестом, площадки не трогаем."""

    def __init__(self) -> None:
        self.prices: dict[str, Snapshot | ParserError] = {}
        self.calls: list[list[ProductRef]] = []

    async def resolve(self, url: str):
        from bot.links import parse_product_url

        return parse_product_url(url)

    async def fetch(self, refs):
        self.calls.append(list(refs))
        return {r: self.prices.get(r.external_id, ParserError("нет данных")) for r in refs}

    async def fetch_one(self, ref):
        result = (await self.fetch([ref]))[ref]
        if isinstance(result, ParserError):
            raise result
        return result

    async def close(self):
        pass


@pytest.fixture
async def db():
    database = await Database(":memory:").connect()
    yield database
    await database.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def hub():
    return FakeHub()
