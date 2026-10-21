"""Авито.

Самая строгая защита из трёх: HTTP-клиент получает «Доступ ограничен: проверка безопасности»
даже с cookies браузера. Поэтому каждое объявление открывается в браузере (без картинок
и шрифтов — так страница грузится за 2–3 секунды), а цена берётся из разметки schema.org
(JSON-LD) — она стабильнее CSS-классов, которые Авито регулярно меняет.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import random
import re

from ..models import Marketplace, ProductRef, Snapshot
from .base import Blocked, FetchResult, ParserError, ProductNotFound, parse_rub
from .browser import BrowserManager

log = logging.getLogger(__name__)

_LD_JSON_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
_CLOSED_MARKERS = ("снято с публикации", "объявление закрыто", "item-view/closed-warning", "Объявление удалено")
_BLOCK_MARKERS = ("Доступ ограничен", "проверка безопасности", "Подтвердите, что вы не робот")


def _ld_objects(page: str):
    for raw in _LD_JSON_RE.findall(page):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        yield from (i for i in items if isinstance(i, dict))


def parse_item(page: str, item_id: str) -> Snapshot:
    title_tag = html.unescape((_TITLE_RE.search(page) or [None, ""])[1])
    if any(marker in title_tag for marker in _BLOCK_MARKERS):
        raise Blocked("Авито: доступ ограничен (антибот)")

    product = next((o for o in _ld_objects(page) if o.get("@type") == "Product"), None)
    closed = any(marker in page for marker in _CLOSED_MARKERS)
    if product is None:
        if closed:
            return Snapshot(title=title_tag.split("|")[0].strip() or f"Объявление {item_id}", price=None,
                            in_stock=False)
        raise ProductNotFound("Объявление не найдено на Авито")

    offer = product.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    price = parse_rub(offer.get("price"))
    availability = str(offer.get("availability", "InStock"))
    in_stock = price is not None and not closed and availability.endswith("InStock")

    image = product.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("contentUrl") or image.get("url")
    if not image and (m := _OG_IMAGE_RE.search(page)):
        image = html.unescape(m.group(1))

    return Snapshot(
        title=html.unescape(product.get("name") or f"Объявление {item_id}"),
        price=price if in_stock else None,
        in_stock=in_stock,
        image_url=image,
    )


class AvitoParser:
    marketplace = Marketplace.AVITO

    def __init__(self, browser: BrowserManager, *, delay: tuple[float, float] = (3, 7)) -> None:
        self.browser = browser
        self.delay = delay

    async def fetch_one(self, ref: ProductRef) -> Snapshot:
        async with self.browser.page("avito", block_media=True) as page:
            resp = await page.goto(ref.url, wait_until="domcontentloaded", timeout=45_000)
            status = resp.status if resp else 0
            if status == 404:
                raise ProductNotFound("Объявление не найдено на Авито")
            if status in (403, 429):
                raise Blocked(f"Авито: доступ ограничен (HTTP {status})")
            try:
                await page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=8000)
            except Exception:  # noqa: BLE001 — разметки может не быть у закрытого объявления
                pass
            content = await page.content()
        return parse_item(content, ref.external_id)

    async def fetch_many(self, refs: list[ProductRef]) -> FetchResult:
        result: FetchResult = {}
        for i, ref in enumerate(refs):
            if i:
                await asyncio.sleep(random.uniform(*self.delay))
            try:
                result[ref.external_id] = await self.fetch_one(ref)
            except ParserError as exc:
                result[ref.external_id] = exc
                if isinstance(exc, Blocked):
                    # IP попал под ограничение — не добиваем его, остальное проверим в следующий раз
                    for rest in refs[i + 1:]:
                        result[rest.external_id] = exc
                    break
            except Exception as exc:  # noqa: BLE001
                log.warning("Авито: ошибка %s: %r", ref.external_id, exc)
                result[ref.external_id] = ParserError(f"Авито: {exc}")
        return result

    async def close(self) -> None:
        pass
