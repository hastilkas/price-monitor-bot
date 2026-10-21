from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from ..links import needs_resolve, parse_product_url
from ..models import Marketplace, ProductRef, Snapshot
from .avito import AvitoParser
from .base import Blocked, FetchResult, Parser, ParserError, ProductNotFound
from .browser import BrowserManager, BrowserUnavailable
from .ozon import OzonParser
from .wildberries import WildberriesParser

log = logging.getLogger(__name__)


def fetch_timeout(count: int) -> float:
    """Запас на запуск браузера и антибот-проверку + время на каждый товар (Авито — самый медленный)."""
    return 120 + 20 * count


__all__ = [
    "Blocked", "BrowserManager", "BrowserUnavailable", "ParserError", "ParserHub", "ProductNotFound",
]


class ParserHub:
    """Единая точка входа: раскладывает товары по площадкам и опрашивает их параллельно."""

    def __init__(self, parsers: dict[Marketplace, Parser], browser: BrowserManager | None = None) -> None:
        self.parsers = parsers
        self.browser = browser

    @classmethod
    def build(cls, *, headless: bool, channel: str | None, proxy: str | None, wb_dest: int) -> "ParserHub":
        browser = BrowserManager(headless=headless, channel=channel, proxy=proxy)
        return cls({
            Marketplace.WB: WildberriesParser(browser, dest=wb_dest, proxy=proxy),
            Marketplace.OZON: OzonParser(browser, proxy=proxy),
            Marketplace.AVITO: AvitoParser(browser),
        }, browser)

    async def resolve(self, url: str) -> ProductRef | None:
        if needs_resolve(url):
            ozon = self.parsers.get(Marketplace.OZON)
            return await ozon.resolve_short_link(url) if isinstance(ozon, OzonParser) else None
        return parse_product_url(url)

    async def fetch(self, refs: list[ProductRef]) -> dict[ProductRef, Snapshot | ParserError]:
        groups: dict[Marketplace, list[ProductRef]] = defaultdict(list)
        for ref in refs:
            groups[ref.marketplace].append(ref)

        async def run(mp: Marketplace, items: list[ProductRef]) -> tuple[list[ProductRef], FetchResult]:
            try:
                return items, await asyncio.wait_for(self.parsers[mp].fetch_many(items), fetch_timeout(len(items)))
            except asyncio.TimeoutError:
                # браузер мог зависнуть — перезапустим его при следующей проверке, а не ждём вечно
                log.warning("%s: проверка %d товаров не уложилась в отведённое время", mp.label, len(items))
                if self.browser is not None:
                    await self.browser.restart()
                return items, {r.external_id: ParserError("превышено время ожидания") for r in items}
            except ParserError as exc:
                return items, {r.external_id: exc for r in items}
            except BrowserUnavailable as exc:
                return items, {r.external_id: ParserError(str(exc)) for r in items}

        out: dict[ProductRef, Snapshot | ParserError] = {}
        for items, res in await asyncio.gather(*(run(mp, items) for mp, items in groups.items())):
            for ref in items:
                out[ref] = res.get(ref.external_id) or ParserError("нет ответа")
        return out

    async def fetch_one(self, ref: ProductRef) -> Snapshot:
        result = (await self.fetch([ref]))[ref]
        if isinstance(result, ParserError):
            raise result
        return result

    async def close(self) -> None:
        for parser in self.parsers.values():
            await parser.close()
        if self.browser is not None:
            await self.browser.close()
