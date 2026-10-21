"""Решение «слать ли уведомление» — чистые функции без сети и БД, полностью покрыты тестами."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .models import Snapshot, Subscription


class AlertKind(str, Enum):
    PRICE_DROP = "drop"
    PRICE_UP = "up"
    TARGET = "target"
    BACK_IN_STOCK = "back"
    OUT_OF_STOCK = "out"


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    old_price: int | None
    new_price: int | None

    @property
    def change_percent(self) -> float | None:
        if self.old_price and self.new_price is not None:
            return (self.new_price - self.old_price) * 100 / self.old_price
        return None


def evaluate(sub: Subscription, prev: Snapshot | None, new: Snapshot) -> Alert | None:
    """Одно уведомление на подписку за проверку — самое важное из сработавших условий.

    prev — состояние на прошлой проверке. Процент снижения считаем не от прошлой проверки,
    а от baseline_price: так ловим и плавное снижение «по 2% в день».
    """
    if prev is None:
        return None  # первая проверка: сравнивать не с чем

    if sub.notify_stock and prev.in_stock != new.in_stock:
        if new.in_stock:
            return Alert(AlertKind.BACK_IN_STOCK, prev.price, new.price)
        return Alert(AlertKind.OUT_OF_STOCK, prev.price, None)

    if not new.in_stock or new.price is None:
        return None

    if sub.target_price is not None and new.price <= sub.target_price and (
        prev.price is None or prev.price > sub.target_price or not prev.in_stock
    ):
        return Alert(AlertKind.TARGET, prev.price, new.price)

    if sub.any_change:
        if prev.price is not None and new.price != prev.price:
            kind = AlertKind.PRICE_DROP if new.price < prev.price else AlertKind.PRICE_UP
            return Alert(kind, prev.price, new.price)
        return None

    base = sub.baseline_price if sub.baseline_price is not None else prev.price
    if base is not None and new.price < base:
        drop = (base - new.price) * 100 / base
        if drop >= sub.drop_percent:
            return Alert(AlertKind.PRICE_DROP, base, new.price)
    return None


def next_baseline(sub: Subscription, new: Snapshot, alert: Alert | None) -> int | None:
    """Новая точка отсчёта процента снижения.

    После уведомления отсчёт идёт от новой цены, а при росте — от нового пика,
    чтобы «подорожал на 30%, потом подешевел на 10%» тоже считалось снижением.
    """
    if new.price is None or not new.in_stock:
        return sub.baseline_price
    if alert is not None or sub.baseline_price is None or new.price > sub.baseline_price:
        return new.price
    return sub.baseline_price
