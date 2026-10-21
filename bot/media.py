"""Фото товара для карточки. WB отдаёт webp, а Telegram надёжно принимает только JPEG/PNG."""
from __future__ import annotations

import io
import logging
from collections import OrderedDict

from curl_cffi.requests import AsyncSession
from PIL import Image

log = logging.getLogger(__name__)


class PhotoCache:
    def __init__(self, proxy: str | None = None, size: int = 200) -> None:
        self._http = AsyncSession(impersonate="chrome", proxy=proxy, timeout=15)
        self._cache: OrderedDict[str, bytes | None] = OrderedDict()
        self._size = size

    async def get(self, url: str | None) -> bytes | None:
        if not url:
            return None
        if url in self._cache:
            self._cache.move_to_end(url)
            return self._cache[url]
        photo = None
        try:
            resp = await self._http.get(url)
            if resp.status_code == 200 and resp.content:
                photo = _to_jpeg(resp.content)
        except Exception as exc:  # noqa: BLE001 — без фото карточка всё равно отправится текстом
            log.debug("Фото %s не загрузилось: %r", url, exc)
        self._cache[url] = photo
        if len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return photo

    async def close(self) -> None:
        await self._http.close()


def _to_jpeg(data: bytes) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        img.thumbnail((1000, 1000))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=88)
        return out.getvalue()
    except Exception:  # noqa: BLE001 — не картинка (страница-заглушка антибота и т.п.)
        return None
