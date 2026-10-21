"""Парсеры на сохранённых реальных ответах площадок (октябрь 2026) — без сети."""
import pytest

from bot.parsers.avito import parse_item
from bot.parsers.base import Blocked, ProductNotFound, parse_rub
from bot.parsers.ozon import parse_page
from bot.parsers.wildberries import image_url, parse_products

from conftest import load_json, load_text


def test_wb_in_stock_and_out_of_stock():
    snaps = parse_products(load_json("wb_cards.json"))
    tws = snaps["839226871"]
    assert tws.in_stock
    assert tws.price == 1592 and tws.old_price == 2525  # копейки → рубли
    assert tws.discount_percent == 37
    assert tws.title == "TehnoVolna / Наушники беспроводные TWS Pro 2"
    assert tws.stock_qty == 49 and tws.seller == "Me TradeMark"

    lamp = snaps["169684889"]
    assert not lamp.in_stock and lamp.price is None


def test_wb_takes_cheapest_size_in_stock():
    data = {"products": [{"id": 1234567, "name": "Кроссовки", "totalQuantity": 3, "sizes": [
        {"stocks": [{"qty": 1}], "price": {"basic": 500000, "product": 450000}},
        {"stocks": [{"qty": 2}], "price": {"basic": 500000, "product": 399000}},
        {"stocks": [], "price": {"basic": 500000, "product": 100000}},  # нет в наличии — не считаем
    ]}]}
    assert parse_products(data)["1234567"].price == 3990


def test_wb_image_url():
    assert image_url(839226871).endswith("/vol8392/part839226/839226871/images/big/1.webp")


def test_ozon_product():
    s = parse_page(load_json("ozon_product.json"), "5343983969")
    assert s.in_stock
    assert (s.price, s.card_price, s.old_price) == (1846, 1681, 20000)
    assert s.title.startswith("Наушники беспроводные с микрофоном")
    assert s.image_url.startswith("https://ir.ozone.ru/")
    assert s.seller == "Электро Мир"


def test_ozon_not_found():
    with pytest.raises(ProductNotFound):
        parse_page(load_json("ozon_not_found.json"), "123456789")


def test_avito_item():
    s = parse_item(load_text("avito_item.html"), "8224149642")
    assert s.in_stock and s.price == 28990
    assert s.title == "iPhone 15, 128 ГБ, 2 SIM"
    assert s.image_url


def test_avito_closed_item():
    page = load_text("avito_item.html").replace("http://schema.org/InStock", "http://schema.org/OutOfStock")
    s = parse_item(page, "8224149642")
    assert not s.in_stock and s.price is None


def test_avito_antibot_page():
    with pytest.raises(Blocked):
        parse_item("<html><title>Доступ ограничен: проверка безопасности</title></html>", "1")


@pytest.mark.parametrize("raw, value", [
    ("1 846 ₽", 1846), ("1 846 ₽", 1846), ("20 000 ₽", 20000), ("1 599,90 ₽", 1599),
    ("28990", 28990), (1846.4, 1846), (None, None), ("цена не указана", None),
])
def test_parse_rub(raw, value):
    assert parse_rub(raw) == value
