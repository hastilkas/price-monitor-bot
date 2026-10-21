"""Модели предметной области. Все цены — целые рубли."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Marketplace(str, Enum):
    WB = "wb"
    OZON = "ozon"
    AVITO = "avito"

    @property
    def label(self) -> str:
        return {"wb": "Wildberries", "ozon": "Ozon", "avito": "Авито"}[self.value]

    @property
    def emoji(self) -> str:
        return {"wb": "🟣", "ozon": "🔵", "avito": "🟢"}[self.value]


@dataclass(frozen=True)
class ProductRef:
    """Ссылка на товар, приведённая к каноническому виду."""

    marketplace: Marketplace
    external_id: str
    url: str


@dataclass(frozen=True)
class Snapshot:
    """Состояние товара на момент проверки."""

    title: str
    price: int | None  # цена, которую видит покупатель; None — нет в продаже
    in_stock: bool
    old_price: int | None = None  # зачёркнутая цена «до скидки»
    card_price: int | None = None  # цена по карте Ozon / с WB-кошельком
    image_url: str | None = None
    seller: str | None = None
    stock_qty: int | None = None  # остаток, если площадка его отдаёт (WB)

    @property
    def discount_percent(self) -> int | None:
        if self.price and self.old_price and self.old_price > self.price:
            return round((self.old_price - self.price) * 100 / self.old_price)
        return None


@dataclass
class Product:
    id: int
    marketplace: Marketplace
    external_id: str
    url: str
    title: str
    image_url: str | None
    price: int | None
    old_price: int | None
    card_price: int | None
    in_stock: bool
    stock_qty: int | None
    min_price: int | None
    max_price: int | None
    first_price: int | None
    checked_at: datetime | None
    fail_count: int
    last_error: str | None

    @property
    def ref(self) -> ProductRef:
        return ProductRef(self.marketplace, self.external_id, self.url)

    def snapshot(self) -> Snapshot | None:
        """Последнее известное состояние (None, если товар ещё ни разу не проверяли)."""
        if self.checked_at is None:
            return None
        return Snapshot(title=self.title, price=self.price, in_stock=self.in_stock, old_price=self.old_price,
                        card_price=self.card_price, image_url=self.image_url, stock_qty=self.stock_qty)


@dataclass
class Subscription:
    """Что именно пользователь хочет знать о товаре."""

    id: int
    user_id: int
    product_id: int
    drop_percent: float  # 0 — любое снижение
    target_price: int | None  # уведомить, когда цена опустится до этой суммы
    any_change: bool  # режим селлера: любое изменение цены, в т.ч. рост
    notify_stock: bool  # появление / исчезновение из продажи
    baseline_price: int | None  # от неё считаем процент снижения
    created_at: datetime


@dataclass(frozen=True)
class PricePoint:
    ts: datetime
    price: int | None
    card_price: int | None
    in_stock: bool
