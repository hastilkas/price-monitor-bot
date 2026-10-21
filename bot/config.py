"""Настройки бота из переменных окружения (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database: Path
    tz: ZoneInfo
    check_interval_minutes: int
    max_products_per_user: int
    proxy_url: str | None
    browser_headless: bool
    browser_channel: str | None
    wb_dest: int
    demo_mode: bool


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def load_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    env = os.environ.get

    token = env("BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN не задан. Скопируйте .env.example в .env и вставьте токен от @BotFather.")

    try:
        admin_ids = frozenset(int(x) for x in env("ADMIN_IDS", "").replace(" ", "").split(",") if x)
    except ValueError as exc:
        raise ConfigError("ADMIN_IDS должен быть списком числовых Telegram ID через запятую") from exc

    interval = int(env("CHECK_INTERVAL_MINUTES", "30"))
    if interval < 5:
        raise ConfigError("CHECK_INTERVAL_MINUTES меньше 5 — маркетплейсы быстро заблокируют IP")

    channel = env("BROWSER_CHANNEL", "chrome").strip()
    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        database=_path(env("DATABASE", "data/prices.db")),
        tz=ZoneInfo(env("TIMEZONE", "Europe/Moscow")),
        check_interval_minutes=interval,
        max_products_per_user=int(env("MAX_PRODUCTS_PER_USER", "30")),
        proxy_url=env("PROXY_URL", "").strip() or None,
        browser_headless=_bool(env("BROWSER_HEADLESS", "true")),
        browser_channel=None if channel.lower() in {"", "chromium"} else channel,
        wb_dest=int(env("WB_DEST", "-1257786")),
        demo_mode=_bool(env("DEMO_MODE", "false")),
    )
