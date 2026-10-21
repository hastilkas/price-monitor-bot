"""Тексты сообщений и форматирование. Всё пользовательское экранируется (parse_mode=HTML)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .alerts import Alert, AlertKind
from .models import Product, Subscription

NBSP = " "


def rub(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", NBSP) + f"{NBSP}₽"


def short(title: str, limit: int = 60) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def pct(value: float) -> str:
    sign = "−" if value < 0 else "+"
    number = f"{abs(value):.1f}".rstrip("0").rstrip(".")
    return f"{sign}{number}%"


def local_time(ts: datetime | None, tz: ZoneInfo) -> str:
    return ts.astimezone(tz).strftime("%d.%m %H:%M") if ts else "—"


def rule_text(sub: Subscription) -> str:
    if sub.any_change:
        parts = ["любое изменение цены"]
    elif sub.drop_percent:
        parts = [f"снижение от {sub.drop_percent:g}%"]
    else:
        parts = ["любое снижение цены"]
    if sub.target_price is not None:
        parts.append(f"цена ≤ {rub(sub.target_price)}")
    if sub.notify_stock:
        parts.append("наличие")
    return " · ".join(parts)


WELCOME = (
    "Привет, {name}! 👋\n\n"
    "Я слежу за ценами на <b>Wildberries</b>, <b>Ozon</b> и <b>Авито</b> и пишу, когда товар "
    "подешевел, достиг нужной цены или снова появился в наличии.\n\n"
    "<b>Как начать:</b> пришлите ссылку на товар — можно сразу несколько, по одной на строку.\n\n"
    "📈 График цены и 📊 отчёт в Excel — в карточке каждого товара."
)

HELP = (
    "<b>Что я умею</b>\n\n"
    "🔗 <b>Добавить товар</b> — пришлите ссылку. Подходят ссылки из браузера и из приложений:\n"
    "• <code>wildberries.ru/catalog/12345678/detail.aspx</code>\n"
    "• <code>ozon.ru/product/…-123456789/</code> и короткие <code>ozon.ru/t/…</code>\n"
    "• <code>avito.ru/moskva/…_1234567890</code>\n\n"
    "🔔 <b>Уведомления</b> — по умолчанию о любом снижении цены и о наличии. В карточке товара можно "
    "выбрать порог (−5%, −10%, −20%), целевую цену или «любое изменение» — удобно селлерам следить "
    "за конкурентами.\n\n"
    "📋 /list — мои товары\n"
    "📊 /report — отчёт в Excel по всем товарам\n"
    "❓ /help — эта справка\n\n"
    "Проверяю цены каждые ~{interval} мин."
)

ADMIN_HELP = "\n\n<b>Админ:</b> /stats — статистика бота"

NO_LINKS = (
    "Не нашёл ссылку на товар 🤔\n\n"
    "Пришлите ссылку с Wildberries, Ozon или Авито — например, скопируйте её из приложения кнопкой «Поделиться»."
)
NOT_A_PRODUCT = "Это ссылка не на карточку товара: <code>{url}</code>"
LIMIT_REACHED = "Достигнут лимит — {limit} товаров. Удалите ненужные в /list, чтобы добавить новые."
FETCHING = "⏳ Смотрю цену на {marketplace}…"
ALREADY_TRACKING = "Этот товар уже отслеживается 👇"
EMPTY_LIST = "Пока ничего не отслеживаю.\n\nПришлите ссылку на товар с Wildberries, Ozon или Авито 👇"
ASK_TARGET = ("🎯 Пришлите цену в рублях, при которой нужно уведомить.\n\n"
              "Сейчас: <b>{price}</b>. Например: <code>{example}</code>")
BAD_TARGET = "Не понял сумму 🤔 Пришлите число, например <code>1500</code>, или /cancel"
TARGET_SET = "🎯 Готово! Напишу, когда цена опустится до <b>{price}</b>."
TARGET_ALREADY = ("\n\nЦена уже ниже цели — сейчас <b>{price}</b>. "
                  "Следующее уведомление — после нового снижения до цели.")
DELETED = "🗑 Удалил «{title}» из отслеживания."
FETCH_FAILED = ("😔 Не получилось получить данные с {marketplace}: {error}\n\n"
                "Площадка могла временно ограничить доступ — попробуйте через пару минут.")
PRODUCT_GONE = "Товар не найден — возможно, ссылка с ошибкой или карточку удалили."


def welcome(first_name: str) -> str:
    return WELCOME.format(name=escape(first_name or "друг"))


def product_card(p: Product, sub: Subscription | None, tz: ZoneInfo) -> str:
    lines = [f"{p.marketplace.emoji} {p.marketplace.label}", f"<b>{escape(short(p.title, 180))}</b>", ""]
    if p.in_stock and p.price is not None:
        price_line = f"💰 <b>{rub(p.price)}</b>"
        if p.old_price:
            price_line += f"  <s>{rub(p.old_price)}</s>"
            discount = round((p.old_price - p.price) * 100 / p.old_price)
            price_line += f"  −{discount}%"
        lines.append(price_line)
        if p.card_price:
            lines.append(f"💳 С картой Ozon: <b>{rub(p.card_price)}</b>")
        lines.append("📦 В наличии" + (f": {p.stock_qty} шт." if p.stock_qty else ""))
    else:
        lines.append("❌ <b>Нет в наличии</b>" + (f" · последняя цена {rub(p.price)}" if p.price else ""))

    if p.min_price is not None and p.max_price is not None and p.min_price != p.max_price:
        lines.append(f"📉 Мин.: {rub(p.min_price)} · 📈 Макс.: {rub(p.max_price)}")
    if p.first_price and p.price and p.first_price != p.price:
        change = (p.price - p.first_price) * 100 / p.first_price
        lines.append(f"{'🟢' if change < 0 else '🔴'} С начала отслеживания: {pct(change)}")
    if sub is not None:
        lines.append(f"🔔 Уведомлю: {rule_text(sub)}")
    lines.append(f"🕒 Проверено: {local_time(p.checked_at, tz)}")
    if p.fail_count >= 3:
        lines.append("⚠️ Последние проверки не удались — площадка ограничивает доступ, пробую снова.")
    return "\n".join(lines)


ALERT_HEADERS = {
    AlertKind.PRICE_DROP: "📉 <b>Подешевело{change}!</b>",
    AlertKind.PRICE_UP: "📈 <b>Подорожало{change}</b>",
    AlertKind.TARGET: "🎯 <b>Цена достигла цели!</b>",
    AlertKind.BACK_IN_STOCK: "✅ <b>Снова в наличии!</b>",
    AlertKind.OUT_OF_STOCK: "❌ <b>Товар закончился</b>",
}


def alert_text(p: Product, alert: Alert, sub: Subscription | None = None, *, demo: bool = False) -> str:
    change = alert.change_percent
    header = ALERT_HEADERS[alert.kind].format(change=f" на {abs(change):.0f}%" if change else "")
    if demo:
        header += " <i>(демо)</i>"
    lines = [header, "", f"{p.marketplace.emoji} <b>{escape(short(p.title, 150))}</b>", ""]

    if alert.kind is AlertKind.OUT_OF_STOCK:
        lines.append(f"Последняя цена: {rub(alert.old_price)}")
        lines.append("Сообщу, когда товар снова появится.")
    elif alert.old_price is not None and alert.new_price is not None and alert.old_price != alert.new_price:
        diff = alert.new_price - alert.old_price
        sign = "−" if diff < 0 else "+"
        lines.append(f"<s>{rub(alert.old_price)}</s> → <b>{rub(alert.new_price)}</b>  ({sign}{rub(abs(diff))})")
    else:
        lines.append(f"Цена: <b>{rub(alert.new_price)}</b>")

    if alert.kind is not AlertKind.OUT_OF_STOCK:
        if p.card_price:
            lines.append(f"💳 С картой Ozon: {rub(p.card_price)}")
        if p.old_price and p.price:
            lines.append(f"🏷 Скидка площадки: −{round((p.old_price - p.price) * 100 / p.old_price)}%")
        if (alert.kind in (AlertKind.PRICE_DROP, AlertKind.TARGET) and p.min_price is not None
                and alert.new_price is not None and alert.new_price <= p.min_price
                and p.max_price is not None and p.max_price > p.min_price):
            lines.append("🔥 Самая низкая цена за всё время отслеживания")
        if sub is not None and sub.target_price is not None and alert.kind is AlertKind.TARGET:
            lines.append(f"Ваша цель: {rub(sub.target_price)}")
    return "\n".join(lines)


def products_list(items: list[tuple[Product, Subscription]], page: int, pages: int) -> str:
    text = f"📋 <b>Мои товары</b> — {len(items)}\n\nНажмите на товар, чтобы открыть карточку."
    if pages > 1:
        text += f"\n\nСтраница {page + 1} из {pages}"
    return text


def list_button(p: Product) -> str:
    price = rub(p.price) if p.in_stock else "нет в наличии"
    return f"{p.marketplace.emoji} {price} · {short(p.title, 38)}"
