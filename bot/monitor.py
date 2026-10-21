"""Фоновый мониторинг: раз в минуту берём товары, которым пора проверку, и рассылаем алерты."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from .alerts import Alert, evaluate, next_baseline
from .db import Database, utcnow
from .models import Product, Snapshot
from .parsers import ParserError, ParserHub, ProductNotFound

log = logging.getLogger(__name__)

Notifier = Callable[[int, Product, Alert], Awaitable[None]]
MAX_BACKOFF = timedelta(hours=6)


class Monitor:
    def __init__(self, db: Database, hub: ParserHub, notify: Notifier, *, interval_minutes: int,
                 clock: Callable[[], datetime] = utcnow, tick_seconds: float = 60) -> None:
        self.db = db
        self.hub = hub
        self.notify = notify
        self.interval = timedelta(minutes=interval_minutes)
        self.clock = clock
        self.tick_seconds = tick_seconds
        # проверка по расписанию и «Проверить сейчас» не должны обработать один товар дважды
        self._locks: dict[int, asyncio.Lock] = {}

    def next_check(self, now: datetime) -> datetime:
        # ±15%, чтобы товары не проверялись одной пачкой в одну и ту же секунду
        return now + self.interval * random.uniform(0.85, 1.15)

    def retry_at(self, now: datetime, fails: int) -> datetime:
        return now + min(self.interval * 2 ** max(fails - 1, 0), MAX_BACKOFF)

    async def run(self) -> None:
        log.info("Мониторинг запущен: интервал %s", self.interval)
        while True:
            try:
                checked = await self.check_due()
                if checked:
                    log.info("Проверено товаров: %d", checked)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — цикл мониторинга не должен умирать
                log.exception("Ошибка цикла мониторинга")
            await asyncio.sleep(self.tick_seconds)

    async def check_due(self) -> int:
        products = await self.db.due_products(self.clock())
        if not products:
            return 0
        results = await self.hub.fetch([p.ref for p in products])
        for product in products:
            await self._process(product.id, results[product.ref])
        return len(products)

    async def check_now(self, product: Product) -> Product:
        """Внеочередная проверка по кнопке. Алерты тоже рассылаются — как при обычной проверке."""
        result = (await self.hub.fetch([product.ref]))[product.ref]
        await self._process(product.id, result)
        if isinstance(result, ParserError) and not isinstance(result, ProductNotFound):
            raise result
        return await self.db.get_product(product.id)

    async def _process(self, product_id: int, result: Snapshot | ParserError) -> None:
        async with self._locks.setdefault(product_id, asyncio.Lock()):
            product = await self.db.get_product(product_id)  # свежее состояние: его могли обновить, пока ждали
            if product is not None:
                await self._apply(product, result)

    async def _apply(self, product: Product, result: Snapshot | ParserError) -> None:
        now = self.clock()
        if isinstance(result, ProductNotFound):
            # карточку удалили — для подписчиков это «пропал из продажи»
            result = Snapshot(title=product.title, price=None, in_stock=False, image_url=product.image_url)
        if isinstance(result, ParserError):
            fails = await self.db.save_error(product.id, str(result), self.retry_at(now, product.fail_count + 1))
            log.warning("%s %s: %s (ошибок подряд: %d)", product.marketplace.value, product.external_id, result, fails)
            return

        prev = product.snapshot()
        await self.db.save_check(product.id, result, now, self.next_check(now))
        updated = await self.db.get_product(product.id)
        for sub in await self.db.subscribers(product.id):
            alert = evaluate(sub, prev, result)
            baseline = next_baseline(sub, result, alert)
            if baseline != sub.baseline_price:
                await self.db.update_subscription(sub.id, baseline_price=baseline)
            if alert is not None:
                try:
                    await self.notify(sub.user_id, updated, alert)
                except Exception:  # noqa: BLE001 — один недоставленный алерт не ломает остальные
                    log.exception("Не удалось отправить алерт пользователю %s", sub.user_id)
