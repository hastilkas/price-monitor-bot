from __future__ import annotations

import re
from typing import Protocol

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from ..models import Marketplace, ProductRef, Snapshot


class ParserError(Exception):
    """Не удалось получить данные — попробуем на следующей проверке."""


class Blocked(ParserError):
    """Площадка не пустила: антибот, капча, лимит запросов с IP."""


class ProductNotFound(ParserError):
    """Карточки нет: удалена, снята с публикации или ссылка с ошибкой."""


FetchResult = dict[str, "Snapshot | ParserError"]


class Parser(Protocol):
    marketplace: Marketplace

    async def fetch_many(self, refs: list[ProductRef]) -> FetchResult:
        """Результат для каждого external_id: снимок или ошибка конкретного товара."""
        ...

    async def close(self) -> None: ...


_NOT_DIGITS = re.compile(r"[^\d]")


def parse_rub(text: str | int | float | None) -> int | None:
    """«1 846 ₽», «1&thinsp;846», 1846.0 → 1846."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return round(text)
    digits = _NOT_DIGITS.sub("", text.split(",")[0])
    return int(digits) if digits else None


class HttpClient:
    """HTTP-клиент с TLS-отпечатком Chrome. Если соединение повисло или оборвалось —
    один повтор через новую сессию: площадки молча рвут долгие keep-alive соединения."""

    def __init__(self, *, proxy: str | None = None, timeout: float = 15) -> None:
        self._proxy = proxy
        self._timeout = timeout
        self._session = self._new_session()

    def _new_session(self) -> AsyncSession:
        return AsyncSession(impersonate="chrome", proxy=self._proxy, timeout=self._timeout)

    async def get(self, url: str, **kwargs):
        try:
            return await self._session.get(url, **kwargs)
        except RequestException:
            await self._session.close()
            self._session = self._new_session()
            return await self._session.get(url, **kwargs)

    async def close(self) -> None:
        await self._session.close()
