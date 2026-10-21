"""Точка входа: python -m bot"""
from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

from .config import ConfigError, load_settings
from .context import AppContext
from .db import Database
from .handlers import build_router
from .media import PhotoCache
from .monitor import Monitor
from .parsers import ParserHub

log = logging.getLogger("bot")

USER_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="list", description="Мои товары"),
    BotCommand(command="report", description="Отчёт в Excel"),
    BotCommand(command="help", description="Помощь"),
]
ADMIN_COMMANDS = USER_COMMANDS + [BotCommand(command="stats", description="Статистика бота")]


async def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # кириллица в логах Windows-консоли
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as exc:
        log.error("%s", exc)
        sys.exit(1)

    db = await Database(settings.database).connect()
    hub = ParserHub.build(headless=settings.browser_headless, channel=settings.browser_channel,
                          proxy=settings.proxy_url, wb_dest=settings.wb_dest)
    photos = PhotoCache(proxy=settings.proxy_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    app: AppContext | None = None

    async def notify(user_id, product, alert) -> None:
        await app.send_alert(bot, user_id, product, alert)

    monitor = Monitor(db, hub, notify, interval_minutes=settings.check_interval_minutes)
    app = AppContext(settings=settings, db=db, hub=hub, monitor=monitor, photos=photos)

    dp = Dispatcher(storage=MemoryStorage(), app=app)
    dp.include_router(build_router(settings.admin_ids))

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        log.exception("Ошибка при обработке апдейта", exc_info=event.exception)
        update = event.update
        try:
            if update.callback_query:
                await update.callback_query.answer("Что-то пошло не так, попробуйте ещё раз", show_alert=True)
            elif update.message:
                await update.message.answer("Что-то пошло не так 😔 Попробуйте ещё раз или нажмите /start")
        except Exception:  # noqa: BLE001 — не даём упасть обработчику ошибок
            pass
        return True

    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось выставить команды админу %s: %s", admin_id, exc)

    me = await bot.get_me()
    log.info("Бот @%s запущен: интервал=%d мин, прокси=%s, демо=%s", me.username,
             settings.check_interval_minutes, "да" if settings.proxy_url else "нет", settings.demo_mode)
    monitor_task = asyncio.create_task(monitor.run())
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        monitor_task.cancel()
        await hub.close()
        await photos.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
