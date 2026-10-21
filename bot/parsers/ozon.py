"""Ozon.

Прямые запросы получают 403 «Доступ ограничен». Браузер открывает ozon.ru, получает
антибот-cookies, а дальше страница товара читается через тот же JSON API, что использует
сайт (entrypoint-api.bx) — это в десятки раз быстрее и легче рендера страницы.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

from curl_cffi.requests import AsyncSession

from ..links import parse_product_url
from ..models import Marketplace, ProductRef, Snapshot
from .base import Blocked, FetchResult, ParserError, ProductNotFound, parse_rub
from .browser import BrowserManager

log = logging.getLogger(__name__)

HOME_URL = "https://www.ozon.ru/"
API_URL = "https://www.ozon.ru/api/entrypoint-api.bx/page/json/v2"
COOKIES_TTL = 6 * 3600


def _widget(states: dict, prefix: str) -> dict | None:
    for key, value in states.items():
        if key.startswith(prefix + "-"):
            try:
                return json.loads(value) if isinstance(value, str) else value
            except json.JSONDecodeError:
                return None
    return None


def parse_page(data: dict, sku: str) -> Snapshot:
    """JSON страницы товара → снимок."""
    page_type = (data.get("pageInfo") or {}).get("pageType")
    states = data.get("widgetStates") or {}
    if page_type and page_type != "pdp":
        raise ProductNotFound("Товар не найден на Ozon")
    if _widget(states, "error") is not None and _widget(states, "webProductHeading") is None:
        raise ProductNotFound("Товар не найден на Ozon")

    heading = _widget(states, "webProductHeading") or {}
    price_w = _widget(states, "webPrice") or {}
    gallery = _widget(states, "webGallery") or {}
    seller = _widget(states, "webCurrentSeller") or {}
    out_of_stock = _widget(states, "webOutOfStock")

    title = heading.get("title") or (out_of_stock or {}).get("skuName") or f"Товар {sku}"
    price = parse_rub(price_w.get("price"))
    card_price = parse_rub(price_w.get("cardPrice"))
    old_price = parse_rub(price_w.get("originalPrice")) if price_w.get("showOriginalPrice", True) else None
    in_stock = bool(price_w.get("isAvailable", True)) and out_of_stock is None and price is not None

    if card_price is not None and price is not None and card_price >= price:
        card_price = None
    if old_price is not None and price is not None and old_price <= price:
        old_price = None
    return Snapshot(
        title=title,
        price=price if in_stock else None,
        old_price=old_price if in_stock else None,
        card_price=card_price if in_stock else None,
        in_stock=in_stock,
        image_url=gallery.get("coverImage"),
        seller=((seller.get("sellerCell") or {}).get("centerBlock") or {}).get("title", {}).get("text"),
    )


class OzonParser:
    marketplace = Marketplace.OZON

    def __init__(self, browser: BrowserManager, *, proxy: str | None = None, delay: tuple[float, float] = (1, 3)):
        self.browser = browser
        self.delay = delay
        self._http = AsyncSession(impersonate="chrome", proxy=proxy, timeout=25)
        self._cookies: dict[str, str] = {}
        self._cookies_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh_cookies(self) -> None:
        async with self._lock:
            if self._cookies and time.monotonic() - self._cookies_at < 60:
                return
            log.info("Ozon: получаю антибот-cookies через браузер")
            await self.browser.reset_context("ozon")
            async with self.browser.page("ozon") as page:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45_000)
                for _ in range(60):
                    cookies = await self.browser.cookies("ozon")
                    # access-token выдаётся только после успешной антибот-проверки
                    if "__Secure-access-token" in cookies:
                        break
                    await page.wait_for_timeout(500)
                else:
                    raise Blocked("Ozon: браузер не прошёл антибот-проверку")
                await page.wait_for_timeout(1000)
                self._cookies = await self.browser.cookies("ozon")
            self._cookies_at = time.monotonic()

    async def _get(self, path: str) -> tuple[int, dict]:
        for attempt in range(2):
            if not self._cookies or time.monotonic() - self._cookies_at > COOKIES_TTL:
                await self._refresh_cookies()
            resp = await self._http.get(API_URL, params={"url": path}, cookies=self._cookies,
                                        headers={"User-Agent": self.browser.user_agent,
                                                 "Accept": "application/json", "Referer": HOME_URL})
            is_json = resp.headers.get("content-type", "").startswith("application/json")
            if is_json:
                return resp.status_code, resp.json()
            if resp.status_code in (403, 429) and attempt == 0:
                log.info("Ozon: cookies отклонены (%s), обновляю", resp.status_code)
                self._cookies = {}
                continue
            raise Blocked(f"Ozon: HTTP {resp.status_code}")
        raise Blocked("Ozon: антибот не пускает")

    async def fetch_one(self, sku: str) -> Snapshot:
        status, data = await self._get(f"/product/{sku}/")
        if status == 404:
            raise ProductNotFound("Товар не найден на Ozon")
        if status >= 400:
            raise ParserError(f"Ozon: HTTP {status}")
        return parse_page(data, sku)

    async def fetch_many(self, refs: list[ProductRef]) -> FetchResult:
        result: FetchResult = {}
        for i, ref in enumerate(refs):
            if i:
                await asyncio.sleep(random.uniform(*self.delay))
            try:
                result[ref.external_id] = await self.fetch_one(ref.external_id)
            except ParserError as exc:
                result[ref.external_id] = exc
            except Exception as exc:  # noqa: BLE001
                log.warning("Ozon: ошибка %s: %r", ref.external_id, exc)
                result[ref.external_id] = ParserError(f"Ozon: {exc}")
        return result

    async def resolve_short_link(self, url: str) -> ProductRef | None:
        """ozon.ru/t/AbCd из приложения → ссылка на товар (редирект проходим браузером)."""
        async with self.browser.page("ozon", block_media=True) as page:
            await page.goto(url, wait_until="commit", timeout=45_000)
            for _ in range(40):
                if ref := parse_product_url(page.url):
                    return ref
                await page.wait_for_timeout(500)
        return None

    async def close(self) -> None:
        await self._http.close()
