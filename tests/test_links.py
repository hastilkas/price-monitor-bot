import pytest

from bot.links import extract_urls, needs_resolve, parse_product_url
from bot.models import Marketplace


@pytest.mark.parametrize("url, mp, ext_id", [
    ("https://www.wildberries.ru/catalog/839226871/detail.aspx?targetUrl=SN", Marketplace.WB, "839226871"),
    ("https://wildberries.ru/catalog/839226871/detail.aspx", Marketplace.WB, "839226871"),
    ("https://www.wildberries.by/catalog/839226871/detail.aspx", Marketplace.WB, "839226871"),
    ("https://wb.ru/catalog/839226871/detail.aspx", Marketplace.WB, "839226871"),
    ("https://www.ozon.ru/product/naushniki-besprovodnye-5343983969/?at=abc", Marketplace.OZON, "5343983969"),
    ("https://ozon.ru/product/5343983969", Marketplace.OZON, "5343983969"),
    ("https://m.ozon.ru/product/naushniki-5343983969/", Marketplace.OZON, "5343983969"),
    ("https://www.avito.ru/moskva/telefony/iphone_15_128_gb_8224149642?context=H4s", Marketplace.AVITO, "8224149642"),
    ("https://m.avito.ru/moskva/telefony/iphone_15_128_gb_8224149642", Marketplace.AVITO, "8224149642"),
    ("https://avito.ru/8224149642", Marketplace.AVITO, "8224149642"),
])
def test_parse_product_url(url, mp, ext_id):
    ref = parse_product_url(url)
    assert ref is not None
    assert (ref.marketplace, ref.external_id) == (mp, ext_id)


def test_canonical_urls_drop_tracking_params():
    assert parse_product_url("https://wildberries.ru/catalog/123456/detail.aspx?utm=1").url == \
        "https://www.wildberries.ru/catalog/123456/detail.aspx"
    assert parse_product_url("https://www.ozon.ru/product/slug-5343983969/?asb=xyz").url == \
        "https://www.ozon.ru/product/5343983969/"
    assert parse_product_url("https://m.avito.ru/moskva/telefony/iphone_8224149642?x=1").url == \
        "https://www.avito.ru/moskva/telefony/iphone_8224149642"


@pytest.mark.parametrize("url", [
    "https://www.wildberries.ru/brands/apple",
    "https://www.ozon.ru/category/smartfony-15502/",
    "https://www.avito.ru/moskva/telefony",
    "https://example.com/catalog/123456/detail.aspx",
])
def test_not_a_product(url):
    assert parse_product_url(url) is None


def test_extract_urls_from_shared_text():
    text = (
        "Глянь: TWS Pro 2 https://www.wildberries.ru/catalog/839226871/detail.aspx?targetUrl=SN.\n"
        "И вот ещё ozon.ru/t/AbC12 и дубль https://www.wildberries.ru/catalog/839226871/detail.aspx?targetUrl=SN"
    )
    assert extract_urls(text) == [
        "https://www.wildberries.ru/catalog/839226871/detail.aspx?targetUrl=SN",
        "https://ozon.ru/t/AbC12",
    ]
    assert extract_urls("просто текст без ссылок") == []


def test_ozon_short_links_need_resolve():
    assert needs_resolve("https://ozon.ru/t/AbC12")
    assert not needs_resolve("https://www.ozon.ru/product/5343983969/")
    assert not needs_resolve("https://www.wildberries.ru/catalog/839226871/detail.aspx")
