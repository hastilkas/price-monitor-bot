"""Мониторинг целиком: база + логика алертов, сеть подменена."""
from bot.alerts import AlertKind
from bot.links import parse_product_url
from bot.monitor import Monitor
from bot.parsers import Blocked, ProductNotFound

from conftest import snap

URL = "https://www.wildberries.ru/catalog/839226871/detail.aspx"


async def setup(db, hub, clock, *, users=(1,), price=1000):
    sent = []

    async def notify(user_id, product, alert):
        sent.append((user_id, product, alert))

    monitor = Monitor(db, hub, notify, interval_minutes=30, clock=clock)
    ref = parse_product_url(URL)
    product = await db.add_product(ref, snap(price), clock(), clock())
    for uid in users:
        await db.upsert_user(uid, None, "Тест")
        await db.subscribe(uid, product.id, baseline=price)
    return monitor, product, sent


async def test_price_drop_notifies_every_subscriber_once(db, hub, clock):
    monitor, product, sent = await setup(db, hub, clock, users=(1, 2))
    hub.prices["839226871"] = snap(900)
    clock.advance(minutes=1)
    assert await monitor.check_due() == 1
    assert [(u, a.kind) for u, _, a in sent] == [(1, AlertKind.PRICE_DROP), (2, AlertKind.PRICE_DROP)]
    assert len(hub.calls) == 1  # товар общий — запрос к площадке один на всех

    updated = await db.get_product(product.id)
    assert (updated.price, updated.min_price, updated.max_price, updated.first_price) == (900, 900, 1000, 1000)

    sent.clear()
    assert await monitor.check_due() == 0  # следующая проверка — через ~30 минут
    clock.advance(minutes=40)
    await monitor.check_due()
    assert sent == []  # цена не менялась


async def test_history_stores_only_changes(db, hub, clock):
    monitor, product, _ = await setup(db, hub, clock)
    for price in (1000, 1000, 950, 950, 1100):
        clock.advance(minutes=40)
        hub.prices["839226871"] = snap(price)
        await monitor.check_due()
    assert [p.price for p in await db.history(product.id)] == [1000, 950, 1100]


async def test_errors_back_off_and_do_not_alert(db, hub, clock):
    monitor, product, sent = await setup(db, hub, clock)
    hub.prices["839226871"] = Blocked("антибот")
    clock.advance(minutes=1)
    await monitor.check_due()
    p = await db.get_product(product.id)
    assert p.fail_count == 1 and "антибот" in p.last_error and p.price == 1000
    assert sent == []
    clock.advance(minutes=20)
    assert await monitor.check_due() == 0  # повтор не раньше интервала

    hub.prices["839226871"] = snap(1000)
    clock.advance(minutes=20)
    await monitor.check_due()
    assert (await db.get_product(product.id)).fail_count == 0


async def test_deleted_card_becomes_out_of_stock(db, hub, clock):
    monitor, product, sent = await setup(db, hub, clock)
    hub.prices["839226871"] = ProductNotFound("удалён")
    clock.advance(minutes=1)
    await monitor.check_due()
    assert [a.kind for _, _, a in sent] == [AlertKind.OUT_OF_STOCK]
    p = await db.get_product(product.id)
    assert not p.in_stock and p.price == 1000  # последняя известная цена сохраняется


async def test_unsubscribed_products_are_not_checked(db, hub, clock):
    monitor, product, _ = await setup(db, hub, clock)
    await db.unsubscribe(1, product.id)
    clock.advance(minutes=1)
    assert await monitor.check_due() == 0


async def test_blocked_users_are_skipped(db, hub, clock):
    monitor, product, _ = await setup(db, hub, clock)
    await db.deactivate_user(1)
    clock.advance(minutes=1)
    assert await monitor.check_due() == 0


async def test_check_now(db, hub, clock):
    monitor, product, sent = await setup(db, hub, clock)
    hub.prices["839226871"] = snap(800)
    updated = await monitor.check_now(product)
    assert updated.price == 800
    assert sent[0][2].kind is AlertKind.PRICE_DROP


async def test_hanging_marketplace_does_not_block_others(monkeypatch):
    import asyncio

    import bot.parsers as parsers
    from bot.models import Marketplace

    class Hanging:
        async def fetch_many(self, refs):
            await asyncio.sleep(3600)

    class Fast:
        async def fetch_many(self, refs):
            return {r.external_id: snap(500) for r in refs}

    monkeypatch.setattr(parsers, "fetch_timeout", lambda count: 0.05)
    hub = parsers.ParserHub({Marketplace.AVITO: Hanging(), Marketplace.WB: Fast()})
    avito = parse_product_url("https://www.avito.ru/moskva/telefony/iphone_8224149642")
    wb = parse_product_url(URL)
    result = await hub.fetch([avito, wb])
    assert result[wb].price == 500
    assert "время ожидания" in str(result[avito])
