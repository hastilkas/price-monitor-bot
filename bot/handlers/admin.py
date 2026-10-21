"""Команды администратора."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..context import AppContext
from ..models import Marketplace


def build_admin_router(admin_ids: frozenset[int]) -> Router:
    router = Router(name="admin")
    router.message.filter(lambda m: m.from_user is not None and m.from_user.id in admin_ids)

    @router.message(Command("stats"))
    async def cmd_stats(message: Message, app: AppContext) -> None:
        s = await app.db.stats()
        by_mp = "\n".join(
            f"{mp.emoji} {mp.label}: {s.by_marketplace.get(mp.value, 0)}" for mp in Marketplace
        )
        await message.answer(
            "📊 <b>Статистика</b>\n\n"
            f"👤 Пользователей: {s.users} (отслеживают: {s.active_users})\n"
            f"📦 Товаров: {s.products} · подписок: {s.subscriptions}\n"
            f"{by_mp}\n\n"
            f"⚠️ Товаров с ошибками проверки: {s.failing}\n"
            f"⏱ Интервал проверки: {app.settings.check_interval_minutes} мин"
        )

    return router
