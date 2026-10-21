"""График истории цены — картинка для Telegram."""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .models import PricePoint, Product  # noqa: E402

ACCENT = "#6D28D9"
CARD = "#0EA5E9"
MUTED = "#94A3B8"
MIN_SPAN = timedelta(hours=6)


def _rub(value: float, _pos=None) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def price_chart(product: Product, history: list[PricePoint], now: datetime, tz: ZoneInfo) -> bytes:
    points = [p for p in history if p.price is not None]
    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=130)
    fig.patch.set_facecolor("white")

    title = product.title if len(product.title) <= 70 else product.title[:67] + "…"
    ax.set_title(f"{product.marketplace.label}: {title}", loc="left", fontsize=11, color="#0F172A", pad=12)

    if points:
        # цена держится до следующего изменения → ступенчатый график до текущего момента
        xs = [p.ts.astimezone(tz) for p in points] + [now.astimezone(tz)]
        ys = [p.price for p in points] + [points[-1].price]
        ax.step(xs, ys, where="post", color=ACCENT, linewidth=2.2, label="Цена")
        ax.scatter(xs[:-1], ys[:-1], color=ACCENT, s=18, zorder=3)

        cards = [p for p in points if p.card_price]
        if cards:
            cx = [p.ts.astimezone(tz) for p in cards] + [now.astimezone(tz)]
            cy = [p.card_price for p in cards] + [cards[-1].card_price]
            ax.step(cx, cy, where="post", color=CARD, linewidth=1.6, linestyle="--", label="По карте")

        low = min(points, key=lambda p: p.price)
        high = max(points, key=lambda p: p.price)
        if high.price != low.price:
            ax.annotate(f"мин. {_rub(low.price)}", (low.ts.astimezone(tz), low.price), textcoords="offset points",
                        xytext=(6, -14), ha="left", fontsize=9, color="#16A34A")
            ax.annotate(f"макс. {_rub(high.price)}", (high.ts.astimezone(tz), high.price),
                        textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color="#DC2626")
        ax.annotate(f"сейчас {_rub(ys[-1])}", (xs[-1], ys[-1]), textcoords="offset points", xytext=(-4, 8),
                    ha="right", fontsize=9, color=ACCENT, fontweight="bold")
        floor = min([low.price] + [p.card_price for p in cards])
        pad = max((high.price - floor) * 0.25, high.price * 0.03)
        bottom = max(floor - pad, 0)
        ax.set_ylim(bottom, high.price + pad)
        ax.fill_between(xs, ys, bottom, step="post", alpha=0.08, color=ACCENT)
        if xs[-1] - xs[0] < MIN_SPAN:  # свежий товар: не растягиваем пару минут на всю ширину
            ax.set_xlim(xs[-1] - MIN_SPAN, xs[-1] + MIN_SPAN * 0.05)

        for p in history:  # периоды «нет в наличии» — серые отметки внизу
            if not p.in_stock:
                ax.axvline(p.ts.astimezone(tz), color=MUTED, linestyle=":", linewidth=1)
    else:
        ax.text(0.5, 0.5, "Пока нет данных о цене", ha="center", va="center", transform=ax.transAxes, color=MUTED)

    ax.yaxis.set_major_formatter(FuncFormatter(_rub))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=tz, minticks=3, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m\n%H:%M", tz=tz))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color("#CBD5E1")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(colors="#475569", labelsize=9)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    if any(p.card_price for p in points):
        ax.legend(frameon=False, fontsize=9, loc="upper right")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
