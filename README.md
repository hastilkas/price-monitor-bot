<div align="center">

# 📉 Мониторинг цен Wildberries · Ozon · Авито

**Telegram-бот следит за ценами и наличием товаров и сразу пишет, когда товар подешевел, достиг нужной цены или снова появился в продаже**

Для покупателей, перекупов и селлеров, которые следят за ценами конкурентов

<br>

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-2CA5E0?style=flat-square&logo=telegram&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-patchright-2EAD33?style=flat-square&logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-async-003B57?style=flat-square&logo=sqlite&logoColor=white)
![Excel](https://img.shields.io/badge/Excel-openpyxl-217346?style=flat-square&logo=microsoftexcel&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)
![Tests](https://img.shields.io/badge/tests-65_passed-brightgreen?style=flat-square&logo=pytest&logoColor=white)

</div>

---

## 🎬 Как это выглядит

<p align="center"><b>Ссылка → карточка товара → график, Excel и уведомление о снижении цены</b></p>
<p align="center"><img src="docs/demo.gif" alt="Демо: добавление товара с Wildberries, график, Excel-отчёт и уведомление о снижении цены" width="420"></p>

<p align="center"><b>График цены прямо в Telegram</b> — цена и цена по карте, минимум и максимум</p>
<p align="center"><img src="docs/chart-example.png" alt="График изменения цены товара на Ozon" width="760"></p>

---

## 💼 Какие задачи решает

| 😩 Было | ✅ Стало |
|---|---|
| Каждый день открывать десяток карточек и сравнивать цены вручную | Бот проверяет сам каждые 30 минут и пишет, только когда есть повод |
| Пропустил скидку — товар снова подорожал или закончился | Уведомление приходит в течение получаса после изменения |
| Селлер не знает, когда конкурент снизил цену | Режим «любое изменение»: сообщение и о снижении, и о повышении |
| «Скажите, когда будет дешевле 15 000» | Целевая цена: одно уведомление, когда цена её пересекла |
| Нет истории, чтобы понять, честная ли «скидка 70%» | График и Excel с полной историей, минимумом и максимумом |

---

## ✨ Возможности

<table>
<tr>
<td valign="top" width="50%">

### 🔔 Уведомления

- 📉 Любое снижение цены или порог **−5% / −10% / −20%**
- 🎯 **Целевая цена**: «напиши, когда будет ≤ 1 500 ₽»
- ↕️ **Режим селлера**: любое изменение, включая рост
- ✅ Снова в наличии / ❌ закончился
- 🔥 Отметка «минимальная цена за всё время»
- Плавное снижение «по 2% в день» тоже ловится: процент считается от последнего уведомления или пика, а не от прошлой проверки

</td>
<td valign="top" width="50%">

### 📦 Товары и отчёты

- 🔗 Ссылки из браузера и **из приложений**, включая короткие `ozon.ru/t/…`
- 📋 Несколько ссылок одним сообщением, до 10 за раз
- 💳 Цена по карте Ozon, зачёркнутая цена, скидка, остаток на складе WB
- 📈 График истории цены картинкой
- 📊 **Excel-отчёт**: сводка, история изменений и нативные диаграммы Excel
- 🔄 Проверка по кнопке, 🖼 карточка с фото товара

</td>
</tr>
</table>

### ⚙️ Под капотом

- **Работает с антибот-защитой 2026 года.** Прямые запросы к WB, Ozon и Авито сейчас получают 403 / «Доступ ограничен». Бот проходит проверку настоящим Chrome через [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) и дальше работает экономно:
  - **Wildberries**: браузер раз в несколько часов получает токен, цены берутся тем же JSON API, что и у сайта, **пачками по 50 товаров** за запрос
  - **Ozon**: браузер получает cookies, страница товара читается через JSON API сайта, без рендера
  - **Авито**: страница открывается в браузере без картинок и шрифтов (2–3 с), цена берётся из разметки schema.org, которая стабильнее CSS-классов
- **Браузер не висит в памяти**: запускается по требованию и закрывается после 5 минут простоя
- **Один товар — одна проверка**, даже если его отслеживают 100 человек
- **Бережно к площадкам**: случайный разброс интервала ±15%, паузы между запросами, экспоненциальный backoff при ошибках, остановка запросов к Авито при первом же ограничении по IP
- **История без мусора**: в базу пишется только изменение цены или наличия, а не каждая проверка
- **Логика уведомлений — чистые функции**: покрыта тестами, без сети и базы
- **65 автотестов**: парсеры на сохранённых реальных ответах площадок, мониторинг с подменённым временем и сквозной диалог через диспетчер aiogram

---

## 🔄 Как это работает

```mermaid
sequenceDiagram
    actor U as Пользователь
    participant B as Бот
    participant M as Мониторинг
    participant P as Парсеры
    participant MP as WB / Ozon / Авито

    U->>B: ссылка на товар
    B->>P: первая проверка
    P->>MP: браузер проходит антибот (если токен устарел)
    P->>MP: JSON API / страница товара
    P-->>B: цена, наличие, фото
    B-->>U: карточка товара + настройки уведомлений

    loop каждые ~30 минут
        M->>P: товары, которым пора проверку (пачкой)
        P-->>M: новые цены
        M->>M: история + проверка условий подписок
        M-->>U: 📉 «Подешевело на 12%» + кнопки «График» и «Excel»
    end
```

---

## 🛠 Стек

| | |
|---|---|
| **Язык** | Python 3.10+ (asyncio) |
| **Telegram** | aiogram 3: FSM, CallbackData, роутеры, DI через workflow_data |
| **Парсинг** | patchright (Playwright) + Google Chrome, curl_cffi с TLS-отпечатком Chrome |
| **Хранилище** | SQLite (aiosqlite, WAL) |
| **Отчёты** | openpyxl (Excel с диаграммами), matplotlib (графики), Pillow |
| **Тесты** | pytest, pytest-asyncio |
| **Деплой** | Docker, docker compose |

---

## 🚀 Быстрый старт

**1. Получите токен** у [@BotFather](https://t.me/BotFather) → `/newbot`.

**2. Установите зависимости и браузер:**

```bash
git clone https://github.com/hastilkas/price-monitor-bot.git
cd price-monitor-bot
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
python -m patchright install chrome
```

> Если Google Chrome уже установлен, последняя команда не нужна.

**3. Настройте окружение:** скопируйте `.env.example` в `.env` и впишите `BOT_TOKEN`.

**4. Запустите:**

```bash
python -m bot
```

**5. Пришлите боту ссылку** на любой товар с Wildberries, Ozon или Авито.

---

## 🐳 Деплой на сервер

```bash
git clone https://github.com/hastilkas/price-monitor-bot.git && cd price-monitor-bot
cp .env.example .env && nano .env
docker compose up -d --build
docker compose logs -f
```

<details>
<summary><b>Важно про сервер и IP</b></summary>

<br>

- Маркетплейсы охотнее пускают **российские IP**. На зарубежном VPS укажите российский прокси в `PROXY_URL`: через него пойдут и браузер, и API-запросы. Токен WB привязан к IP, поэтому они должны совпадать.
- Нужно минимум **1 ГБ RAM**: Chrome запускается только на время проверки, но в этот момент ему нужна память.
- Образ собирается под **x86-64** (Google Chrome не выпускается для Linux ARM).
- Если на сервере антибот не пропускает headless-браузер, поставьте `BROWSER_HEADLESS=false`: контейнер сам запустит Chrome на виртуальном дисплее Xvfb.

</details>

---

## 🔧 Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `BOT_TOKEN` | — | Токен от @BotFather **(обязательно)** |
| `ADMIN_IDS` | — | Telegram ID админов через запятую (команда `/stats`) |
| `CHECK_INTERVAL_MINUTES` | `30` | Как часто проверять цены (минимум 5) |
| `MAX_PRODUCTS_PER_USER` | `30` | Лимит товаров на пользователя |
| `PROXY_URL` | — | `http://user:pass@host:port` или `socks5://…` |
| `BROWSER_CHANNEL` | `chrome` | `chrome` — Google Chrome, `chromium` — встроенный |
| `BROWSER_HEADLESS` | `true` | `false` — браузер с окном (на сервере через Xvfb) |
| `WB_DEST` | `-1257786` | Регион доставки WB (цены зависят от региона), по умолчанию Москва |
| `DATABASE` | `data/prices.db` | Путь к базе SQLite |
| `TIMEZONE` | `Europe/Moscow` | Часовой пояс в сообщениях и отчётах |
| `DEMO_MODE` | `false` | Кнопка «Пример уведомления» в карточке, для демонстрации |

---

## 🧪 Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Покрыто: разбор ссылок всех форматов, парсеры на реальных ответах WB, Ozon и Авито (октябрь 2026), все типы уведомлений и их пороги, мониторинг (дедупликация, backoff, удалённые карточки, заблокировавшие бота пользователи), Excel-отчёт и график, **полный диалог** от ссылки до уведомления и отчёта.

---

## 📁 Структура проекта

```
bot/
├── __main__.py          # точка входа, сборка зависимостей
├── config.py            # настройки из .env
├── links.py             # распознавание ссылок WB / Ozon / Авито
├── alerts.py            # когда слать уведомление (чистые функции)
├── monitor.py           # фоновые проверки, история, рассылка алертов
├── db.py                # SQLite: товары, подписки, история цен
├── report.py            # Excel: сводка, история, диаграммы
├── chart.py             # график цены для Telegram
├── media.py             # фото товара (webp → jpeg, кэш)
├── texts.py             # все тексты в одном месте
├── keyboards.py         # клавиатуры и callback-данные
├── handlers/            # сценарии пользователя и админа
└── parsers/
    ├── browser.py       # общий headless-Chrome, закрывается при простое
    ├── wildberries.py   # токен антибота + JSON API пачками
    ├── ozon.py          # cookies антибота + JSON API страницы
    └── avito.py         # страница в браузере + schema.org
tests/                   # unit + e2e, fixtures/ — реальные ответы площадок
```

---

## 🗺 Можно добавить под заказчика

- [ ] Яндекс Маркет, Мегамаркет, AliExpress
- [ ] Мониторинг всей выдачи по запросу или категории, а не отдельных товаров
- [ ] Отслеживание цен конкурентов по своему ассортименту с выгрузкой в Google Таблицу
- [ ] Ротация прокси для тысяч товаров
- [ ] Платная подписка: больше товаров и чаще проверки (Telegram Payments / ЮKassa)
- [ ] Веб-дашборд с историей цен

---

<div align="center">

**Нужен парсер или мониторинг под вашу задачу?** Напишите мне: сделаю под ваши площадки, товары и формат отчётов.

[![Telegram](https://img.shields.io/badge/Написать_в_Telegram-@thehastil-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/thehastil)

</div>
