from __future__ import annotations

import re
from typing import Protocol

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
