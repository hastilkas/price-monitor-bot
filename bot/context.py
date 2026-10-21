from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from . import keyboards as kb
from . import texts
from .alerts import Alert
from .config import Settings
from .db import Database
from .media import PhotoCache
from .models import Product
from .monitor import Monitor
from .parsers import ParserHub

log = logging.getLogger(__name__)

CAPTION_LIMIT = 1024


@dataclass
class AppContext:
    """Всё, что нужно обработчикам. Передаётся в них через workflow_data диспетчера."""

    settings: Settings
    db: Database
    hub: ParserHub
    monitor: Monitor
    photos: PhotoCache
    # (user_id, product_id) → время последней ручной проверки, чтобы не долбить площадку
    manual_checks: dict[tuple[int, int], float] = field(default_factory=dict)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.settings.admin_ids

    async def send_product(self, bot: Bot, chat_id: int, product: Product, text: str,
                           markup: InlineKeyboardMarkup) -> None:
        """Карточка с фото товара; если фото нет или подпись длинная — просто текст."""
        photo = await self.photos.get(product.image_url) if len(text) <= CAPTION_LIMIT else None
        if photo:
            try:
                await bot.send_photo(chat_id, BufferedInputFile(photo, "product.jpg"), caption=text,
                                     reply_markup=markup)
                return
            except TelegramBadRequest as exc:
                log.debug("send_photo не удался, шлю текстом: %s", exc)
        await bot.send_message(chat_id, text, reply_markup=markup, disable_web_page_preview=True)

    async def send_alert(self, bot: Bot, user_id: int, product: Product, alert: Alert, *, demo: bool = False) -> None:
        sub = await self.db.get_subscription(user_id, product.id)
        text = texts.alert_text(product, alert, sub, demo=demo)
        for _ in range(3):
            try:
                await self.send_product(bot, user_id, product, text, kb.alert(product))
                return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
            except TelegramForbiddenError:
                log.info("Пользователь %s заблокировал бота — отключаю его мониторинг", user_id)
                await self.db.deactivate_user(user_id)
                return


async def show(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None, *,
               caption: bool = True) -> None:
    """Редактирует сообщение с кнопками (текст или подпись к фото); если нельзя — присылает новое.

    caption=False — экран не про этот товар (например, список), и подменять подпись под его фото нельзя.
    """
    message = cb.message
    try:
        if isinstance(message, Message):
            if message.photo:
                if caption and len(text) <= CAPTION_LIMIT:
                    await message.edit_caption(caption=text, reply_markup=markup)
                    return
            else:
                await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
                return
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return
        log.debug("edit failed, sending new message: %s", exc)
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=markup, disable_web_page_preview=True)
