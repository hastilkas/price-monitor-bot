"""Клавиатуры и callback_data. Кнопки несут ID товара — работают и после перезапуска бота."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .models import Product, Subscription
from .texts import list_button, rub

PAGE_SIZE = 8

BTN_LIST = "📋 Мои товары"
BTN_REPORT = "📊 Отчёт в Excel"
BTN_HELP = "❓ Помощь"


class ProdCb(CallbackData, prefix="p"):
    action: str  # card | chart | check | rules | report | del | delok | demo
    id: int


class RuleCb(CallbackData, prefix="r"):
    id: int
    rule: str  # any | p5 | p10 | p20 | target | notarget | change | stock


class ListCb(CallbackData, prefix="l"):
    page: int


class MenuCb(CallbackData, prefix="menu"):
    action: str  # report | sample


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_LIST), KeyboardButton(text=BTN_REPORT)], [KeyboardButton(text=BTN_HELP)]],
        resize_keyboard=True,
        input_field_placeholder="Вставьте ссылку на товар…",
    )


def start_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧪 Добавить товар-пример", callback_data=MenuCb(action="sample"))
    return kb.as_markup()


def product_card(p: Product, *, demo: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"🔗 Открыть на {p.marketplace.label}", url=p.url))
    kb.row(
        InlineKeyboardButton(text="📈 График", callback_data=ProdCb(action="chart", id=p.id).pack()),
        InlineKeyboardButton(text="🔄 Проверить", callback_data=ProdCb(action="check", id=p.id).pack()),
    )
    kb.row(InlineKeyboardButton(text="🔔 Условия уведомлений", callback_data=ProdCb(action="rules", id=p.id).pack()))
    kb.row(
        InlineKeyboardButton(text="📊 Excel", callback_data=ProdCb(action="report", id=p.id).pack()),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=ProdCb(action="del", id=p.id).pack()),
    )
    if demo:
        kb.row(InlineKeyboardButton(text="🧪 Пример уведомления", callback_data=ProdCb(action="demo", id=p.id).pack()))
    kb.row(InlineKeyboardButton(text="⬅️ Все товары", callback_data=ListCb(page=0).pack()))
    return kb.as_markup()


def alert(p: Product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"🛒 Открыть на {p.marketplace.label}", url=p.url))
    kb.row(
        InlineKeyboardButton(text="📈 График", callback_data=ProdCb(action="chart", id=p.id).pack()),
        InlineKeyboardButton(text="📊 Скачать отчёт в Excel", callback_data=ProdCb(action="report", id=p.id).pack()),
    )
    kb.row(InlineKeyboardButton(text="⚙️ Карточка товара", callback_data=ProdCb(action="card", id=p.id).pack()))
    return kb.as_markup()


def rules(p: Product, sub: Subscription) -> InlineKeyboardMarkup:
    def mark(active: bool, text: str) -> str:
        return f"✅ {text}" if active else text

    drop_mode = not sub.any_change
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=mark(drop_mode and not sub.drop_percent, "📉 Любое снижение"),
                                callback_data=RuleCb(id=p.id, rule="any").pack()))
    kb.row(*[
        InlineKeyboardButton(text=mark(drop_mode and sub.drop_percent == n, f"−{n}%"),
                             callback_data=RuleCb(id=p.id, rule=f"p{n}").pack())
        for n in (5, 10, 20)
    ])
    kb.row(InlineKeyboardButton(text=mark(sub.any_change, "↕️ Любое изменение (для селлеров)"),
                                callback_data=RuleCb(id=p.id, rule="change").pack()))
    if sub.target_price is None:
        kb.row(InlineKeyboardButton(text="🎯 Целевая цена…", callback_data=RuleCb(id=p.id, rule="target").pack()))
    else:
        kb.row(
            InlineKeyboardButton(text=f"🎯 {rub(sub.target_price)} — изменить",
                                 callback_data=RuleCb(id=p.id, rule="target").pack()),
            InlineKeyboardButton(text="✖️ Убрать цель", callback_data=RuleCb(id=p.id, rule="notarget").pack()),
        )
    kb.row(InlineKeyboardButton(text=f"📦 Наличие: {'вкл' if sub.notify_stock else 'выкл'}",
                                callback_data=RuleCb(id=p.id, rule="stock").pack()))
    kb.row(InlineKeyboardButton(text="⬅️ К товару", callback_data=ProdCb(action="card", id=p.id).pack()))
    return kb.as_markup()


def confirm_delete(p: Product) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Да, удалить", callback_data=ProdCb(action="delok", id=p.id))
    kb.button(text="Отмена", callback_data=ProdCb(action="card", id=p.id))
    return kb.as_markup()


def products_list(items: list[tuple[Product, Subscription]], page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p, _ in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        kb.row(InlineKeyboardButton(text=list_button(p), callback_data=ProdCb(action="card", id=p.id).pack()))
    pages = max(1, -(-len(items) // PAGE_SIZE))
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=ListCb(page=page - 1).pack()))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=ListCb(page=page).pack()))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=ListCb(page=page + 1).pack()))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="📊 Отчёт в Excel по всем", callback_data=MenuCb(action="report").pack()))
    return kb.as_markup()
