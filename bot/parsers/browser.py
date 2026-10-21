"""Общий headless-браузер для прохождения антибот-проверок.

Маркетплейсы в 2026 году отдают данные только «настоящему» браузеру. Поэтому браузер
используется экономно: WB и Ozon — только чтобы получить cookies/токен (раз в несколько часов),
дальше цены идут быстрыми HTTP-запросами. Авито — единственная площадка, где каждая
проверка открывает страницу. Без дела браузер закрывается и не держит память.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)

_PLATFORM_UA = {
    "Windows": "Windows NT 10.0; Win64; x64",
    "Darwin": "Macintosh; Intel Mac OS X 10_15_7",
}


class BrowserUnavailable(RuntimeError):
    pass


class BrowserManager:
    def __init__(self, *, headless: bool = True, channel: str | None = "chrome", proxy: str | None = None,
                 max_pages: int = 2, idle_timeout: float = 300) -> None:
        self.headless = headless
        self.channel = channel or None
        self.proxy = proxy
        self.idle_timeout = idle_timeout
        self._pages = asyncio.Semaphore(max_pages)
        self._lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._contexts: dict[str, object] = {}
        self._user_agent: str | None = None
        self._last_used = 0.0
        self._active = 0
        self._reaper: asyncio.Task | None = None

    @property
    def user_agent(self) -> str:
        """UA обычного (не headless) Chrome той же версии. Токены WB привязаны к UA —
        HTTP-запросы после браузера обязаны слать ровно его."""
        if self._user_agent is None:
            raise BrowserUnavailable("браузер ещё не запускался")
        return self._user_agent

    async def _ensure_browser(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        try:
            from patchright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise BrowserUnavailable("не установлен patchright: pip install patchright") from exc

        if self._pw is None:
            self._pw = await async_playwright().start()
        launch: dict = {"headless": self.headless}
        if self.channel:
            launch["channel"] = self.channel
        if self.proxy:
            launch["proxy"] = _playwright_proxy(self.proxy)
        try:
            self._browser = await self._pw.chromium.launch(**launch)
        except Exception as exc:
            raise BrowserUnavailable(
                f"не удалось запустить браузер ({exc}). Установите Chrome: python -m patchright install chrome"
            ) from exc
        major = self._browser.version.split(".")[0]
        os_part = _PLATFORM_UA.get(platform.system(), "X11; Linux x86_64")
        self._user_agent = (f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 (KHTML, like Gecko) "
                            f"Chrome/{major}.0.0.0 Safari/537.36")
        self._contexts.clear()
        log.info("Браузер запущен: Chrome %s, headless=%s", self._browser.version, self.headless)
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_idle())
        return self._browser

    async def _context(self, name: str):
        """Отдельный набор cookies на каждую площадку."""
        browser = await self._ensure_browser()
        ctx = self._contexts.get(name)
        if ctx is None:
            ctx = await browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow",
                                            user_agent=self.user_agent, viewport={"width": 1366, "height": 900})
            self._contexts[name] = ctx
        return ctx

    @asynccontextmanager
    async def page(self, context: str, *, block_media: bool = False) -> AsyncIterator:
        async with self._pages:
            async with self._lock:
                ctx = await self._context(context)
                self._active += 1
            page = await ctx.new_page()
            if block_media:
                await page.route("**/*", _skip_heavy)
            try:
                yield page
            finally:
                self._last_used = time.monotonic()
                self._active = max(self._active - 1, 0)  # после restart() счётчик уже обнулён
                try:
                    await page.close()
                except Exception:  # noqa: BLE001 — страница могла умереть вместе с браузером
                    pass

    async def cookies(self, context: str) -> dict[str, str]:
        ctx = await self._context(context)
        return {c["name"]: c["value"] for c in await ctx.cookies()}

    async def reset_context(self, context: str) -> None:
        """Сбросить cookies площадки — когда старые перестали пускать."""
        async with self._lock:
            ctx = self._contexts.pop(context, None)
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(30)
            if self._browser is None:
                return
            if self._active == 0 and time.monotonic() - self._last_used > self.idle_timeout:
                async with self._lock:
                    if self._active == 0:
                        log.info("Браузер простаивает %d с — закрываю", self.idle_timeout)
                        await self._shutdown_browser()
                        return

    async def _shutdown_browser(self) -> None:
        browser, self._browser = self._browser, None
        self._contexts.clear()
        if browser is not None:
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass

    async def restart(self) -> None:
        """Закрыть зависший браузер; следующая страница запустит новый."""
        async with self._lock:
            self._active = 0
            await self._shutdown_browser()

    async def close(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
        await self._shutdown_browser()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None


async def _skip_heavy(route) -> None:
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


def _playwright_proxy(url: str) -> dict:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    proxy = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
    if parts.username:
        proxy["username"] = parts.username
        proxy["password"] = parts.password or ""
    return proxy
