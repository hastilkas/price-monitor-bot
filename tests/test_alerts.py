from datetime import datetime

from bot.alerts import AlertKind, evaluate, next_baseline
from bot.models import Subscription

from conftest import snap


def sub(**kw) -> Subscription:
    base = dict(id=1, user_id=1, product_id=1, drop_percent=0, target_price=None, any_change=False,
                notify_stock=True, baseline_price=1000, created_at=datetime(2026, 10, 20))
    base.update(kw)
    return Subscription(**base)


def test_first_check_never_alerts():
    assert evaluate(sub(), None, snap(500)) is None


def test_any_drop():
    alert = evaluate(sub(), snap(1000), snap(990))
    assert alert.kind is AlertKind.PRICE_DROP
    assert (alert.old_price, alert.new_price) == (1000, 990)
    assert round(alert.change_percent, 1) == -1.0


def test_price_rise_is_silent_by_default():
    assert evaluate(sub(), snap(1000), snap(1100)) is None


def test_percent_threshold_counts_from_baseline_not_previous_check():
    s = sub(drop_percent=10, baseline_price=1000)
    assert evaluate(s, snap(1000), snap(950)) is None  # −5%
    alert = evaluate(s, snap(950), snap(900))  # от прошлой проверки −5%, но от точки отсчёта −10%
    assert alert.kind is AlertKind.PRICE_DROP
    assert alert.old_price == 1000


def test_baseline_follows_peaks_and_resets_after_alert():
    s = sub(drop_percent=10, baseline_price=1000)
    assert next_baseline(s, snap(1300), None) == 1300  # подорожало — считаем от пика
    assert next_baseline(s, snap(950), None) == 1000  # снижение без алерта — точку не трогаем
    alert = evaluate(s, snap(950), snap(880))
    assert next_baseline(s, snap(880), alert) == 880  # после алерта — от новой цены
    assert next_baseline(s, snap(None, in_stock=False), None) == 1000


def test_target_price_fires_once_on_crossing():
    s = sub(target_price=900, drop_percent=50)
    alert = evaluate(s, snap(950), snap(899))
    assert alert.kind is AlertKind.TARGET
    assert evaluate(s, snap(899), snap(890)) is None  # уже ниже цели — не повторяем
    assert evaluate(s, snap(1000), snap(900)).kind is AlertKind.TARGET  # снова пересекла


def test_back_in_stock_and_out_of_stock():
    s = sub()
    assert evaluate(s, snap(1000), snap(None, in_stock=False)).kind is AlertKind.OUT_OF_STOCK
    back = evaluate(s, snap(None, in_stock=False), snap(800))
    assert back.kind is AlertKind.BACK_IN_STOCK
    assert back.new_price == 800


def test_stock_alerts_can_be_disabled():
    s = sub(notify_stock=False)
    assert evaluate(s, snap(1000), snap(None, in_stock=False)) is None
    assert evaluate(s, snap(None, in_stock=False), snap(1000)) is None


def test_target_reached_on_restock_even_without_stock_alerts():
    s = sub(notify_stock=False, target_price=900)
    assert evaluate(s, snap(None, in_stock=False), snap(850)).kind is AlertKind.TARGET


def test_seller_mode_reports_any_change():
    s = sub(any_change=True)
    assert evaluate(s, snap(1000), snap(1050)).kind is AlertKind.PRICE_UP
    assert evaluate(s, snap(1050), snap(1000)).kind is AlertKind.PRICE_DROP
    assert evaluate(s, snap(1000), snap(1000)) is None
