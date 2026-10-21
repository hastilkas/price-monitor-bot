"""Сквозной тест: реальный диалог через диспетчер aiogram, подменены только Telegram и площадки."""
from __future__ import annotations

import itertools
from datetime import datetime

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (EditMessageCaption, EditMessageText, SendDocument, SendMessage, SendPhoto,
                             TelegramMethod)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.alerts import AlertKind
from bot.config import Settings
from bot.context import AppContext
from bot.handlers import build_router
from bot.handlers.user import parse_target
from bot.monitor import Monitor

from conftest import TZ, snap

USER = User(id=111, is_bot=False, first_name="Анна", username="anna")
ADMIN_ID = 999
WB_URL = "https://www.wildberries.ru/catalog/839226871/detail.aspx?targetUrl=SN"
_ids = itertools.count(1)
# Роутеры aiogram подключаются один раз, поэтому диспетчер общий на модуль
DP = Dispatcher(storage=MemoryStorage())
DP.include_router(build_router(frozenset({ADMIN_ID})))


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, (SendMessage, EditMessageText, SendPhoto, SendDocument, EditMessageCaption)):
            chat_id = getattr(method, "chat_id", None) or USER.id
            return Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=chat_id, type="private"),
                           text=getattr(method, "text", None)).as_(bot)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def close(self):
        pass


class NoPhotos:
    async def get(self, url):
        return None


class Harness:
    def __init__(self, app: AppContext) -> None:
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.app = app

    def _msg(self, user: User = USER, **kw) -> Message:
        return Message(message_id=next(_ids), date=datetime.now(), chat=Chat(id=user.id, type="private"),
                       from_user=user, **kw)

    async def send(self, text: str, user: User = USER):
        self.session.calls.clear()
        await DP.feed_update(self.bot, Update(update_id=next(_ids), message=self._msg(user, text=text)), app=self.app)
        return self.session.calls

    async def press(self, callback_data: str):
        self.session.calls.clear()
        cb = CallbackQuery(id=str(next(_ids)), from_user=USER, chat_instance="x", data=callback_data,
                           message=self._msg(text="old"))
        await DP.feed_update(self.bot, Update(update_id=next(_ids), callback_query=cb), app=self.app)
        return self.session.calls

    @staticmethod
    def buttons(calls) -> dict[str, str]:
        out = {}
        for c in calls:
            for row in getattr(getattr(c, "reply_markup", None), "inline_keyboard", None) or []:
                for b in row:
                    out[b.text] = b.callback_data or b.url
        return out

    @staticmethod
    def texts(calls) -> str:
        return "\n".join(getattr(c, "text", None) or getattr(c, "caption", None) or "" for c in calls)


@pytest.fixture
async def h(db, hub, clock):
    settings = Settings(bot_token="42:TEST", admin_ids=frozenset({ADMIN_ID}), database=None, tz=TZ,
                        check_interval_minutes=30, max_products_per_user=2, proxy_url=None,
                        browser_headless=True, browser_channel=None, wb_dest=-1257786, demo_mode=True)
    harness: Harness | None = None

    async def notify(user_id, product, alert):
        await app.send_alert(harness.bot, user_id, product, alert)

    monitor = Monitor(db, hub, notify, interval_minutes=30, clock=clock)
    app = AppContext(settings=settings, db=db, hub=hub, monitor=monitor, photos=NoPhotos())
    harness = Harness(app)
    hub.prices["839226871"] = snap(1592, old_price=2525, title="TehnoVolna / Наушники TWS Pro 2", stock_qty=49)
    return harness


async def test_full_flow(h, hub, clock):
    calls = await h.send("/start")
    assert "Wildberries" in h.texts(calls)

    # ссылка из приложения WB → карточка товара
    calls = await h.send(f"Смотри какие наушники {WB_URL}")
    text = h.texts(calls)
    assert "TehnoVolna / Наушники TWS Pro 2" in text
    assert "1 592 ₽" in text and "−37%" in text and "49 шт." in text
    assert "любое снижение цены" in text
    card = h.buttons(calls)
    assert card["🔗 Открыть на Wildberries"] == "https://www.wildberries.ru/catalog/839226871/detail.aspx"

    # повторная ссылка — без дубля
    calls = await h.send(WB_URL)
    assert "уже отслеживается" in h.texts(calls)

    # условие «−10%»
    calls = await h.press(card["🔔 Условия уведомлений"])
    rules = h.buttons(calls)
    calls = await h.press(rules["−10%"])
    assert "снижение от 10%" in h.texts(calls)

    # целевая цена через ввод суммы
    await h.press(rules["🎯 Целевая цена…"])
    calls = await h.send("1 400 ₽")
    assert "1 400 ₽" in h.texts(calls)

    # цена упала на 5% — ниже порога, молчим; упала до цели — алерт с кнопкой Excel
    clock.advance(minutes=40)
    hub.prices["839226871"] = snap(1510, title="TehnoVolna / Наушники TWS Pro 2")
    h.session.calls.clear()
    await h.app.monitor.check_due()
    assert h.session.calls == []

    clock.advance(minutes=40)
    hub.prices["839226871"] = snap(1390, title="TehnoVolna / Наушники TWS Pro 2")
    await h.app.monitor.check_due()
    alert_text = h.texts(h.session.calls)
    assert "Цена достигла цели" in alert_text and "1 390 ₽" in alert_text
    alert_buttons = h.buttons(h.session.calls)
    assert "📊 Скачать отчёт в Excel" in alert_buttons

    # отчёт и график
    calls = await h.press(alert_buttons["📊 Скачать отчёт в Excel"])
    docs = [c for c in calls if isinstance(c, SendDocument)]
    assert docs and docs[0].document.filename.endswith(".xlsx")
    calls = await h.press(alert_buttons["📈 График"])
    assert any(isinstance(c, SendPhoto) for c in calls)

    # список и удаление
    calls = await h.send("📋 Мои товары")
    assert "Мои товары</b> — 1" in h.texts(calls)
    calls = await h.press(card["🗑 Удалить"])
    calls = await h.press(h.buttons(calls)["🗑 Да, удалить"])
    assert "Удалил" in h.texts(calls)
    assert await h.app.db.user_products(USER.id) == []


async def test_demo_alert_button(h):
    calls = await h.send(WB_URL)
    calls = await h.press(h.buttons(calls)["🧪 Пример уведомления"])
    text = h.texts(calls)
    assert "Подешевело" in text and "(демо)" in text


async def test_limit_and_unknown_links(h, hub):
    hub.prices["5343983969"] = snap(1846)
    hub.prices["4404449496"] = snap(1824)
    await h.send(WB_URL)
    await h.send("https://www.ozon.ru/product/5343983969/")
    calls = await h.send("https://www.ozon.ru/product/4404449496/")
    assert "лимит" in h.texts(calls)

    calls = await h.send("https://www.ozon.ru/category/smartfony-15502/")
    assert "не на карточку товара" in h.texts(calls)
    calls = await h.send("привет")
    assert "Не нашёл ссылку" in h.texts(calls)


async def test_fetch_failure_is_reported(h, hub):
    from bot.parsers import Blocked

    hub.prices["839226871"] = Blocked("Ozon: антибот не пускает")
    calls = await h.send(WB_URL)
    assert "Не получилось получить данные" in h.texts(calls)
    assert await h.app.db.user_products(USER.id) == []


async def test_stats_only_for_admin(h):
    admin = User(id=ADMIN_ID, is_bot=False, first_name="Admin")
    assert "Статистика" in h.texts(await h.send("/stats", user=admin))
    assert "Статистика" not in h.texts(await h.send("/stats"))


@pytest.mark.parametrize("raw, value", [("1500", 1500), ("1 500 ₽", 1500), ("1500,50 руб", 1500),
                                        ("0", None), ("дёшево", None)])
def test_parse_target(raw, value):
    assert parse_target(raw) == value


def test_alert_kinds_have_texts():
    from bot.texts import ALERT_HEADERS

    assert set(ALERT_HEADERS) == set(AlertKind)
