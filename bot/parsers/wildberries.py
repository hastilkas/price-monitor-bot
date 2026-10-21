"""Wildberries.

С осени 2026 публичный card.wb.ru закрыт антиботом «wbaas»: без токена любой запрос — 403/498.
Схема: браузер один раз открывает wildberries.ru и проходит JS-проверку → получаем cookie
x_wbaas_token (живёт ~1,5 суток, привязан к IP и User-Agent). Дальше цены берём тем же API,
что и сайт, — пачками до 50 артикулов за запрос, без браузера.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from ..models import Marketplace, ProductRef, Snapshot
from .base import Blocked, FetchResult, HttpClient, ParserError, ProductNotFound
from .browser import BrowserManager

log = logging.getLogger(__name__)

API_URL = "https://www.wildberries.ru/__internal/u-card/cards/v4/detail"
HOME_URL = "https://www.wildberries.ru/"
TOKEN_COOKIE = "x_wbaas_token"
TOKEN_TTL = 12 * 3600  # обновляем с запасом, не дожидаясь отказа
BATCH = 50
# Все CDN-узлы geobasket отдают любую картинку; номер узла — просто балансировка
IMAGE_HOSTS = 60


def image_url(nm: int) -> str:
    vol, part = nm // 100_000, nm // 1000
    host = f"mow-basket-cdn-{vol % IMAGE_HOSTS + 1:02d}.geobasket.ru"
    return f"https://{host}/vol{vol}/part{part}/{nm}/images/big/1.webp"


def parse_products(data: dict) -> dict[str, Snapshot]:
    """Ответ cards/v4/detail → снимки по артикулам. Цены в API — в копейках."""
    out: dict[str, Snapshot] = {}
    for p in data.get("products") or []:
        nm = int(p["id"])
        best: tuple[int, int | None] | None = None
        for size in p.get("sizes") or []:
            price = size.get("price") or {}
            if not size.get("stocks") or not price.get("product"):
                continue
            current = round(price["product"] / 100)
            basic = round(price["basic"] / 100) if price.get("basic") else None
            if best is None or current < best[0]:
                best = (current, basic)
        qty = p.get("totalQuantity")
        in_stock = best is not None and (qty is None or qty > 0)
        title = p.get("name") or f"Товар {nm}"
        if p.get("brand"):
            title = f"{p['brand']} / {title}"
        out[str(nm)] = Snapshot(
            title=title,
            price=best[0] if best else None,
            old_price=best[1] if best and best[1] and best[1] > best[0] else None,
            in_stock=in_stock,
            image_url=image_url(nm),
            seller=p.get("supplier"),
            stock_qty=qty,
        )
    return out


class WildberriesParser:
    marketplace = Marketplace.WB

    def __init__(self, browser: BrowserManager, *, dest: int = -1257786, proxy: str | None = None) -> None:
        self.browser = browser
        self.dest = dest
        self._http = HttpClient(proxy=proxy)
        self._cookies: dict[str, str] = {}
        self._token_at = 0.0
        self._device_id = "site_" + uuid.uuid4().hex
        self._token_lock = asyncio.Lock()

    async def _refresh_token(self) -> None:
        async with self._token_lock:
            if time.monotonic() - self._token_at < 60 and self._cookies:
                return  # пока ждали замок, токен уже обновил другой запрос
            log.info("WB: получаю антибот-токен через браузер")
            await self.browser.reset_context("wb")
            async with self.browser.page("wb") as page:
                await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45_000)
                for _ in range(60):
                    cookies = await self.browser.cookies("wb")
                    if TOKEN_COOKIE in cookies:
                        break
                    await page.wait_for_timeout(500)
                else:
                    raise Blocked("WB: браузер не прошёл антибот-проверку за 30 секунд")
            self._cookies = cookies
            self._token_at = time.monotonic()

    async def _request(self, ids: list[str]) -> dict:
        params = {"appType": 1, "curr": "rub", "dest": self.dest, "spp": 30, "lang": "ru", "nm": ";".join(ids)}
        for attempt in range(2):
            if not self._cookies or time.monotonic() - self._token_at > TOKEN_TTL:
                await self._refresh_token()
            headers = {
                "User-Agent": self.browser.user_agent,
                "deviceid": self._device_id,
                "x-requested-with": "XMLHttpRequest",
                "Referer": HOME_URL,
                "Accept-Language": "ru-RU,ru;q=0.9",
            }
            resp = await self._http.get(API_URL, params=params, headers=headers, cookies=self._cookies)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403, 498) and attempt == 0:
                log.info("WB: токен отклонён (%s), обновляю", resp.status_code)
                self._cookies = {}
                continue
            if resp.status_code == 429:
                raise Blocked("WB: слишком много запросов (429)")
            raise ParserError(f"WB: HTTP {resp.status_code}")
        raise Blocked("WB: антибот не принимает токен")

    async def fetch_many(self, refs: list[ProductRef]) -> FetchResult:
        result: FetchResult = {}
        ids = [r.external_id for r in refs]
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            try:
                snapshots = parse_products(await self._request(chunk))
            except ParserError as exc:
                result.update({nm: exc for nm in chunk})
                continue
            except Exception as exc:  # noqa: BLE001 — сеть, битый JSON
                log.warning("WB: ошибка запроса: %r", exc)
                result.update({nm: ParserError(f"WB: {exc}") for nm in chunk})
                continue
            for nm in chunk:
                result[nm] = snapshots.get(nm) or ProductNotFound("Товар не найден на Wildberries")
        return result

    async def close(self) -> None:
        await self._http.close()
