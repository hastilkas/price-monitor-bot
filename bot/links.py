"""Распознавание ссылок на товары. Принимаем всё, чем делятся из браузера и приложений."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import Marketplace, ProductRef

URL_RE = re.compile(r"(?:https?://)?(?:[\w-]+\.)*(?:wildberries|wb|ozon|avito)\.(?:ru|by|kz|am|kg|uz)/[^\s<>\"']*",
                    re.IGNORECASE)

_WB_RE = re.compile(r"/catalog/(\d{5,12})(?:/|$)")
_OZON_RE = re.compile(r"/product/(?:[\w-]*-)?(\d{5,12})(?:/|$)")
_OZON_SHORT_RE = re.compile(r"^/t/[\w-]+/?$")
_AVITO_RE = re.compile(r"_(\d{7,12})/?$")
_AVITO_BARE_RE = re.compile(r"^/(\d{7,12})/?$")


def extract_urls(text: str) -> list[str]:
    """Все ссылки на поддерживаемые площадки из произвольного текста, без дублей, в исходном порядке."""
    seen: dict[str, None] = {}
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?)]}»")
        if not url.lower().startswith("http"):
            url = "https://" + url
        seen.setdefault(url)
    return list(seen)


def _host(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.lower().removeprefix("www.").removeprefix("m.")


def needs_resolve(url: str) -> bool:
    """Короткие ссылки из приложения Ozon (ozon.ru/t/AbCd) ведут на товар только после редиректа."""
    return _host(url).startswith("ozon.") and bool(_OZON_SHORT_RE.match(urlsplit(url).path))


def parse_product_url(url: str) -> ProductRef | None:
    """Ссылка → площадка, ID и каноническая ссылка. None — это не карточка товара."""
    host = _host(url)
    path = urlsplit(url).path

    if host.startswith(("wildberries.", "wb.")):
        if m := _WB_RE.search(path):
            nm = m.group(1)
            return ProductRef(Marketplace.WB, nm, f"https://www.wildberries.ru/catalog/{nm}/detail.aspx")

    elif host.startswith("ozon."):
        if m := _OZON_RE.search(path):
            sku = m.group(1)
            return ProductRef(Marketplace.OZON, sku, f"https://www.ozon.ru/product/{sku}/")

    elif host.startswith("avito."):
        if m := _AVITO_RE.search(path):
            return ProductRef(Marketplace.AVITO, m.group(1), f"https://www.avito.ru{path.rstrip('/')}")
        if m := _AVITO_BARE_RE.match(path):
            return ProductRef(Marketplace.AVITO, m.group(1), f"https://www.avito.ru/{m.group(1)}")

    return None
