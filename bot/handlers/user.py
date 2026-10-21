"""Сценарий пользователя: добавить товар по ссылке → карточка → график / отчёт / условия уведомлений."""
from __future__ import annotations

import asyncio
import re
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import keyboards as kb
from .. import texts
from ..alerts import Alert, AlertKind
from ..chart import price_chart
from ..context import AppContext, show
from ..links import extract_urls
from ..models import Product, Subscription
from ..parsers import ParserError, ProductNotFound
from ..report import build_report

router = Router(name="user")

MAX_LINKS_PER_MESSAGE = 10
MANUAL_CHECK_COOLDOWN = 60
FRESH_SECONDS = 15 * 60  # товар, недавно проверенный для другого пользователя, при добавлении не перепроверяем
# Товары для кнопки «Добавить товар-пример»: пробуем по очереди, пока один не откроется
SAMPLE_URLS = (
    "https://www.wildberries.ru/catalog/839226871/detail.aspx",
    "https://www.ozon.ru/product/5343983969/",
    "https://www.wildberries.ru/catalog/169684889/detail.aspx",
)


class TargetForm(StatesGroup):
    price = State()


def _message_urls(message: Message) -> list[str]:
    """Ссылки из текста, подписи и «скрытых» ссылок (текст с гиперссылкой, пересланные посты)."""
    text = message.text or message.caption or ""
    hidden = [e.url for e in (message.entities or message.caption_entities or []) if e.type == "text_link" and e.url]
    return extract_urls("\n".join([text, *hidden]))


def _pages(items: list) -> int:
    return max(1, -(-len(items) // kb.PAGE_SIZE))


async def _send_card(bot: Bot, chat_id: int, product: Product, sub: Subscription | None, app: AppContext) -> None:
    await app.send_product(bot, chat_id, product, texts.product_card(product, sub, app.settings.tz),
                           kb.product_card(product, demo=app.settings.demo_mode))


# --- меню ------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, app: AppContext) -> None:
    await state.clear()
    user = message.from_user
    await app.db.upsert_user(user.id, user.username, user.first_name)
    await message.answer(texts.welcome(user.first_name), reply_markup=kb.main_menu())
    await message.answer("Нет ссылки под рукой? Начните с примера 👇", reply_markup=kb.start_actions())


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def cmd_help(message: Message, app: AppContext) -> None:
    text = texts.HELP.format(interval=app.settings.check_interval_minutes)
    if app.is_admin(message.from_user.id):
        text += texts.ADMIN_HELP
    await message.answer(text, reply_markup=kb.main_menu(), disable_web_page_preview=True)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменил 👌", reply_markup=kb.main_menu())


# --- добавление товаров ----------------------------------------------------
async def add_product(bot: Bot, chat_id: int, user_id: int, url: str, app: AppContext) -> bool:
    try:
        ref = await app.hub.resolve(url)
    except Exception:  # noqa: BLE001 — короткая ссылка Ozon не раскрылась
        ref = None
    if ref is None:
        await bot.send_message(chat_id, texts.NOT_A_PRODUCT.format(url=texts.short(url, 80)),
                               disable_web_page_preview=True)
        return False

    existing = await app.db.find_product(ref)
    if existing is not None and (sub := await app.db.get_subscription(user_id, existing.id)):
        await bot.send_message(chat_id, texts.ALREADY_TRACKING)
        await _send_card(bot, chat_id, existing, sub, app)
        return False
    if await app.db.count_user_products(user_id) >= app.settings.max_products_per_user:
        await bot.send_message(chat_id, texts.LIMIT_REACHED.format(limit=app.settings.max_products_per_user))
        return False

    now = app.monitor.clock()
    if existing is not None and existing.checked_at and (now - existing.checked_at).total_seconds() < FRESH_SECONDS:
        product = existing
    else:
        status = await bot.send_message(chat_id, texts.FETCHING.format(marketplace=ref.marketplace.label))
        try:
            snap = await app.hub.fetch_one(ref)
        except ProductNotFound:
            await status.edit_text(texts.PRODUCT_GONE)
            return False
        except ParserError as exc:
            await status.edit_text(texts.FETCH_FAILED.format(marketplace=ref.marketplace.label, error=exc))
            return False
        product = await app.db.add_product(ref, snap, now, app.monitor.next_check(now))
        await status.delete()

    sub = await app.db.subscribe(user_id, product.id, baseline=product.price if product.in_stock else None)
    await _send_card(bot, chat_id, product, sub, app)
    return True


@router.callback_query(kb.MenuCb.filter(F.action == "sample"))
async def on_sample(cb: CallbackQuery, bot: Bot, app: AppContext) -> None:
    await cb.answer("Добавляю пример…")
    user = cb.from_user
    await app.db.upsert_user(user.id, user.username, user.first_name)
    for url in SAMPLE_URLS:
        existing = await app.db.find_product(await app.hub.resolve(url))
        if existing is not None and await app.db.get_subscription(user.id, existing.id):
            continue
        if await add_product(bot, user.id, user.id, url, app):
            return
    await bot.send_message(user.id, "Пришлите ссылку на любой товар с Wildberries, Ozon или Авито 👇")


# --- список и карточка -----------------------------------------------------
async def _owned(cb: CallbackQuery, app: AppContext, product_id: int) -> Product | None:
    product = await app.db.get_product(product_id)
    if product is None or await app.db.get_subscription(cb.from_user.id, product_id) is None:
        await cb.answer("Этот товар уже не отслеживается", show_alert=True)
        return None
    return product


@router.message(Command("list"))
@router.message(F.text == kb.BTN_LIST)
async def cmd_list(message: Message, app: AppContext) -> None:
    items = await app.db.user_products(message.from_user.id)
    if not items:
        await message.answer(texts.EMPTY_LIST, reply_markup=kb.start_actions())
        return
    await message.answer(texts.products_list(items, 0, _pages(items)), reply_markup=kb.products_list(items, 0))


@router.callback_query(kb.ListCb.filter())
async def on_list_page(cb: CallbackQuery, callback_data: kb.ListCb, app: AppContext) -> None:
    items = await app.db.user_products(cb.from_user.id)
    await cb.answer()
    if not items:
        await show(cb, texts.EMPTY_LIST, kb.start_actions(), caption=False)
        return
    page = min(max(callback_data.page, 0), _pages(items) - 1)
    await show(cb, texts.products_list(items, page, _pages(items)), kb.products_list(items, page), caption=False)


@router.callback_query(kb.ProdCb.filter(F.action == "card"))
async def on_card(cb: CallbackQuery, callback_data: kb.ProdCb, bot: Bot, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await cb.answer()
    sub = await app.db.get_subscription(cb.from_user.id, product.id)
    if isinstance(cb.message, Message) and cb.message.photo:
        await show(cb, texts.product_card(product, sub, app.settings.tz),
                   kb.product_card(product, demo=app.settings.demo_mode))
    else:  # из текстового списка — новое сообщение с фото товара
        await _send_card(bot, cb.from_user.id, product, sub, app)


@router.callback_query(kb.ProdCb.filter(F.action == "check"))
async def on_check(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    key = (cb.from_user.id, product.id)
    wait = MANUAL_CHECK_COOLDOWN - (time.monotonic() - app.manual_checks.get(key, -1e9))
    if wait > 0:
        await cb.answer(f"Проверял только что. Ещё раз — через {int(wait) + 1} с", show_alert=True)
        return
    app.manual_checks[key] = time.monotonic()
    await cb.answer("🔄 Проверяю цену…")
    try:
        product = await app.monitor.check_now(product)
    except ParserError as exc:
        await cb.message.answer(texts.FETCH_FAILED.format(marketplace=product.marketplace.label, error=exc))
        return
    sub = await app.db.get_subscription(cb.from_user.id, product.id)
    await show(cb, texts.product_card(product, sub, app.settings.tz),
               kb.product_card(product, demo=app.settings.demo_mode))


@router.callback_query(kb.ProdCb.filter(F.action == "chart"))
async def on_chart(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await cb.answer("Рисую график…")
    history = await app.db.history(product.id)
    png = await asyncio.to_thread(price_chart, product, history, app.monitor.clock(), app.settings.tz)
    changes = sum(1 for p in history if p.price is not None)
    caption = f"📈 {texts.short(product.title, 80)}\nИзменений цены: {max(changes - 1, 0)}"
    if changes < 2:
        caption += "\n\nГрафик наполнится, когда цена начнёт меняться — я проверяю её регулярно."
    await cb.message.answer_photo(BufferedInputFile(png, "chart.png"), caption=caption)


# --- Excel-отчёт -----------------------------------------------------------
async def _report_to(message: Message, app: AppContext, items: list[tuple[Product, Subscription]]) -> None:
    histories = {p.id: await app.db.history(p.id) for p, _ in items}
    now = app.monitor.clock()
    data = await asyncio.to_thread(build_report, items, histories, now, app.settings.tz)
    stamp = now.astimezone(app.settings.tz).strftime("%Y-%m-%d_%H-%M")
    if len(items) == 1:
        p = items[0][0]
        name = f"{p.marketplace.value}_{p.external_id}_{stamp}.xlsx"
    else:
        name = f"prices_{stamp}.xlsx"
    await message.answer_document(BufferedInputFile(data, name),
                                  caption="📊 Отчёт по ценам: сводка, история изменений и графики")


async def _send_report(cb: CallbackQuery, app: AppContext, product_id: int | None) -> None:
    items = await app.db.user_products(cb.from_user.id)
    if product_id is not None:
        items = [(p, s) for p, s in items if p.id == product_id]
    if not items:
        await cb.answer("Нет товаров для отчёта", show_alert=True)
        return
    await cb.answer("Готовлю отчёт…")
    await _report_to(cb.message, app, items)


@router.callback_query(kb.ProdCb.filter(F.action == "report"))
async def on_report_one(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    await _send_report(cb, app, callback_data.id)


@router.callback_query(kb.MenuCb.filter(F.action == "report"))
async def on_report_all(cb: CallbackQuery, app: AppContext) -> None:
    await _send_report(cb, app, None)


@router.message(Command("report"))
@router.message(F.text == kb.BTN_REPORT)
async def cmd_report(message: Message, app: AppContext) -> None:
    items = await app.db.user_products(message.from_user.id)
    if not items:
        await message.answer(texts.EMPTY_LIST, reply_markup=kb.start_actions())
        return
    await _report_to(message, app, items)


# --- удаление --------------------------------------------------------------
@router.callback_query(kb.ProdCb.filter(F.action == "del"))
async def on_delete(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await cb.answer()
    await show(cb, f"Удалить «{texts.short(product.title, 80)}» из отслеживания?", kb.confirm_delete(product))


@router.callback_query(kb.ProdCb.filter(F.action == "delok"))
async def on_delete_ok(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await app.db.unsubscribe(cb.from_user.id, product.id)
    await cb.answer("Удалено")
    await show(cb, texts.DELETED.format(title=texts.short(product.title, 80)))


# --- демо-уведомление ------------------------------------------------------
@router.callback_query(kb.ProdCb.filter(F.action == "demo"))
async def on_demo_alert(cb: CallbackQuery, callback_data: kb.ProdCb, bot: Bot, app: AppContext) -> None:
    """Реального изменения цены приходится ждать, поэтому в демо уведомление можно увидеть сразу."""
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await cb.answer()
    if product.in_stock and product.price:
        alert = Alert(AlertKind.PRICE_DROP, round(product.price * 1.15 / 10) * 10, product.price)
    else:
        alert = Alert(AlertKind.OUT_OF_STOCK, product.price, None)
    await app.send_alert(bot, cb.from_user.id, product, alert, demo=True)


# --- условия уведомлений ---------------------------------------------------
@router.callback_query(kb.ProdCb.filter(F.action == "rules"))
async def on_rules(cb: CallbackQuery, callback_data: kb.ProdCb, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    await cb.answer()
    sub = await app.db.get_subscription(cb.from_user.id, product.id)
    await show(cb, texts.product_card(product, sub, app.settings.tz), kb.rules(product, sub))


@router.callback_query(kb.RuleCb.filter())
async def on_rule(cb: CallbackQuery, callback_data: kb.RuleCb, state: FSMContext, app: AppContext) -> None:
    if not (product := await _owned(cb, app, callback_data.id)):
        return
    sub = await app.db.get_subscription(cb.from_user.id, product.id)
    rule = callback_data.rule
    current = product.price if product.in_stock else None

    if rule == "target":
        await cb.answer()
        await state.set_state(TargetForm.price)
        await state.update_data(product_id=product.id)
        example = round((product.price or 1000) * 0.9 / 10) * 10
        await cb.message.answer(texts.ASK_TARGET.format(price=texts.rub(product.price), example=example))
        return

    if rule == "any":
        changes = {"drop_percent": 0, "any_change": False, "baseline_price": current}
    elif rule in {"p5", "p10", "p20"}:
        changes = {"drop_percent": float(rule[1:]), "any_change": False, "baseline_price": current}
    elif rule == "change":
        changes = {"any_change": not sub.any_change}
    elif rule == "stock":
        changes = {"notify_stock": not sub.notify_stock}
    elif rule == "notarget":
        changes = {"target_price": None}
    else:
        await cb.answer()
        return

    await app.db.update_subscription(sub.id, **changes)
    sub = await app.db.get_subscription(cb.from_user.id, product.id)
    await cb.answer(f"Уведомлю: {texts.rule_text(sub)}")
    await show(cb, texts.product_card(product, sub, app.settings.tz), kb.rules(product, sub))


_PRICE_RE = re.compile(r"^\s*(\d[\d\s]*)(?:[.,]\d{1,2})?\s*(?:₽|р\.?|руб\.?|rub)?\s*$", re.IGNORECASE)


def parse_target(text: str) -> int | None:
    """«1500», «1 500 ₽», «1500,50 руб» → 1500."""
    m = _PRICE_RE.match(text or "")
    if not m:
        return None
    value = int(re.sub(r"\s", "", m.group(1)))
    return value if value > 0 else None


@router.message(TargetForm.price, F.text)
async def on_target_price(message: Message, state: FSMContext, bot: Bot, app: AppContext) -> None:
    value = parse_target(message.text)
    if value is None:
        await message.answer(texts.BAD_TARGET)
        return
    data = await state.get_data()
    await state.clear()
    product = await app.db.get_product(data["product_id"])
    sub = await app.db.get_subscription(message.from_user.id, product.id) if product else None
    if sub is None:
        await message.answer("Этот товар уже не отслеживается")
        return
    await app.db.update_subscription(sub.id, target_price=value)
    sub = await app.db.get_subscription(message.from_user.id, product.id)
    text = texts.TARGET_SET.format(price=texts.rub(value))
    if product.in_stock and product.price is not None and product.price <= value:
        text += texts.TARGET_ALREADY.format(price=texts.rub(product.price))
    await message.answer(text, reply_markup=kb.main_menu())
    await _send_card(bot, message.chat.id, product, sub, app)


# --- ссылки: ловит любой текст, поэтому регистрируется последним -------------
@router.message(StateFilter(None), F.text | F.caption)
async def on_links(message: Message, bot: Bot, app: AppContext) -> None:
    urls = _message_urls(message)
    if not urls:
        await message.answer(texts.NO_LINKS, reply_markup=kb.main_menu())
        return
    user = message.from_user
    await app.db.upsert_user(user.id, user.username, user.first_name)
    if len(urls) > MAX_LINKS_PER_MESSAGE:
        await message.answer(f"Добавлю первые {MAX_LINKS_PER_MESSAGE} ссылок из {len(urls)}.")
    for url in urls[:MAX_LINKS_PER_MESSAGE]:
        await add_product(bot, message.chat.id, user.id, url, app)
