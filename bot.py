#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VINTAGE CLIENT FINDER
Поиск потенциальных покупателей винтажной одежды.

Источники:
- Bing RSS search
- DuckDuckGo HTML search, если доступен
- Avito, Юла и другие площадки через индексируемые страницы
- VK API (опционально)
- YouTube Data API (опционально)
- Reddit public search (опционально)
- Публичные Telegram-каналы, указанные в настройках
- Дополнительные RSS-ленты

Переменные GitHub Actions:
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
VK_TOKEN                 (необязательно)
YOUTUBE_API_KEY          (необязательно)
TELEGRAM_CHANNELS        (необязательно, через запятую)
EXTRA_RSS                (необязательно, RSS URL через запятую)
MAX_QUERIES              (необязательно, по умолчанию 24)
REQUEST_DELAY            (необязательно, по умолчанию 0.4)

Используются только доступные публичные источники.
"""

import os
import re
import json
import time
import html
import hashlib
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
SEEN_FILE = BASE_DIR / "seen.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

VK_TOKEN = os.getenv("VK_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

TELEGRAM_CHANNELS = [
    x.strip().lstrip("@")
    for x in os.getenv("TELEGRAM_CHANNELS", "").split(",")
    if x.strip()
]

EXTRA_RSS = [
    x.strip()
    for x in os.getenv("EXTRA_RSS", "").split(",")
    if x.strip()
]

MAX_QUERIES = max(1, int(os.getenv("MAX_QUERIES", "24")))
REQUEST_DELAY = max(0.0, float(os.getenv("REQUEST_DELAY", "0.4")))
MAX_ALERTS = max(1, int(os.getenv("MAX_ALERTS_PER_RUN", "25")))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
)

# ============================================================
# SEARCH TERMS
# ============================================================

BUY_INTENT = [
    '"ищу винтажную одежду"',
    '"куплю винтажную одежду"',
    '"где купить винтаж"',
    '"посоветуйте винтажный магазин"',
    '"ищу винтажку"',
    '"ищу одежду y2k"',
    '"куплю одежду y2k"',
    '"ищу Carhartt"',
    '"ищу Dickies"',
    '"ищу Levi\'s"',
    '"где купить Carhartt"',
    '"ищу винтажную куртку"',
    '"ищу старые джинсы"',
    '"ищу оригинальную вещь"',
    '"кто продаёт винтаж"',
    '"где достать винтаж"',
    '"ищу архивную одежду"',
    '"ищу редкую одежду"',
    '"куплю винтажные джинсы"',
    '"ищу одежду 90-х"',
    '"ищу одежду 2000-х"',
    '"ищу секонд-хенд"',
    '"подскажите где купить одежду"',
    '"ищу такую куртку"',
    '"ищу такие джинсы"',
    '"looking for vintage clothing"',
    '"where to buy vintage clothes"',
    '"looking for Y2K clothes"',
]

CLOTHING = [
    "винтажная куртка",
    "джинсы",
    "кожаная куртка",
    "бомбер",
    "ветровка",
    "рабочая куртка",
    "карго",
    "футболка",
    "лонгслив",
    "свитшот",
    "худи",
    "спортивная куртка",
    "флиска",
    "жилет",
    "рубашка",
    "пальто",
    "кроссовки",
    "сумка",
    "джинсовка",
]

STYLES = [
    "vintage",
    "винтаж",
    "Y2K",
    "ретро",
    "90s",
    "80s",
    "2000s",
    "streetwear",
    "grunge",
    "workwear",
    "gorpcore",
    "архивная одежда",
    "секонд-хенд",
]

BRANDS = [
    "Levi's",
    "Carhartt",
    "Dickies",
    "Ralph Lauren",
    "Tommy Hilfiger",
    "Diesel",
    "Nike",
    "Adidas",
    "Reebok",
    "The North Face",
    "Patagonia",
    "Stone Island",
    "Stussy",
    "Supreme",
    "Wrangler",
    "Lee",
    "Champion",
    "Umbro",
    "Lacoste",
    "Burberry",
    "Oakley",
    "Columbia",
    "Eddie Bauer",
    "Guess",
    "Fila",
    "Polo Sport",
    "Helly Hansen",
]

CITIES = [
    "Москва",
    "Санкт-Петербург",
    "Екатеринбург",
    "Казань",
    "Новосибирск",
    "Краснодар",
    "Сочи",
    "Ростов-на-Дону",
    "Самара",
    "Нижний Новгород",
    "Челябинск",
    "Уфа",
    "Пермь",
    "Воронеж",
    "Красноярск",
    "Омск",
    "Тюмень",
]

MARKETPLACES = [
    "avito.ru",
    "youla.ru",
    "meshok.net",
    "farpost.ru",
]

SOCIAL_SITES = [
    "vk.com",
    "threads.net",
    "threads.com",
    "t.me",
    "reddit.com",
    "youtube.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
    "pikabu.ru",
]

NEGATIVE_TERMS = [
    "вакансия",
    "ищу работу",
    "работа продавцом",
    "оптовая продажа",
    "поставщик",
    "дропшиппинг",
    "пошив на заказ",
    "своё производство",
    "свое производство",
]

BUY_WORDS = [
    "ищу",
    "куплю",
    "хочу купить",
    "где купить",
    "где найти",
    "посоветуйте",
    "подскажите",
    "кто продаёт",
    "кто продает",
    "нужен",
    "нужна",
    "нужно",
    "хочу найти",
    "looking for",
    "where to buy",
    "want to buy",
    "recommend",
]

SELLER_WORDS = [
    "продаю",
    "продам",
    "в наличии",
    "новое поступление",
    "оптом",
    "поставщик",
    "каталог",
]


# ============================================================
# HELPERS
# ============================================================

def log(message):
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}] "
        f"{message}",
        flush=True,
    )


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(url):
    url = html.unescape(str(url or "")).strip()

    if url.startswith("//"):
        url = "https:" + url

    try:
        parsed = urllib.parse.urlsplit(url)

        if parsed.scheme not in ("http", "https"):
            return ""

        query = [
            (key, value)
            for key, value in urllib.parse.parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )
            if not key.lower().startswith("utm_")
            and key.lower() not in ("fbclid", "gclid", "yclid")
        ]

        return urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            urllib.parse.urlencode(query),
            "",
        ))

    except Exception:
        return ""


def fetch(url, headers=None, data=None, method="GET", timeout=15):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, body.decode(charset, errors="replace")

    except urllib.error.HTTPError as error:
        return error.code, ""

    except Exception as error:
        log(f"Источник временно недоступен: {urllib.parse.urlsplit(url).netloc}: {error}")
        return 0, ""


def load_seen():
    try:
        result = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def save_seen(seen):
    if len(seen) > 25000:
        seen = dict(list(seen.items())[-20000:])

    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fingerprint(item):
    identity = item.get("url") or (
        item.get("title", "") + item.get("text", "")
    )

    return hashlib.sha256(
        identity.encode("utf-8", errors="ignore")
    ).hexdigest()


# ============================================================
# LEAD SCORING
# ============================================================

def score_lead(item):
    text = (
        item.get("title", "")
        + " "
        + item.get("text", "")
        + " "
        + item.get("query", "")
    ).lower()

    score = 0
    signals = []

    intents = [
        term for term in BUY_WORDS
        if term.lower() in text
    ]

    clothing = [
        term for term in CLOTHING + STYLES
        if term.lower() in text
    ]

    brands = [
        brand for brand in BRANDS
        if brand.lower() in text
    ]

    if intents:
        score += min(40, 20 + 5 * (len(intents) - 1))
        signals.append("намерение: " + ", ".join(intents[:3]))

    if clothing:
        score += min(30, 8 + 4 * len(clothing))
        signals.append("товар/стиль: " + ", ".join(clothing[:4]))

    if brands:
        score += min(20, 8 + 4 * len(brands))
        signals.append("бренд: " + ", ".join(brands[:3]))

    if any(city.lower() in text for city in CITIES):
        score += 5
        signals.append("город России")

    if any(term in text for term in NEGATIVE_TERMS):
        score -= 25
        signals.append("возможный продавец/оптовик")

    if any(term in text for term in SELLER_WORDS) and not intents:
        score -= 15

    score = max(0, min(100, score))

    if score >= 60:
        level = "🔥 ВЫСОКИЙ"
    elif score >= 35:
        level = "🟡 СРЕДНИЙ"
    else:
        level = "🔎 НИЗКИЙ"

    return score, level, signals


def create_item(source, title, url, text="", date="", query=""):
    url = normalize_url(url)

    if not url:
        return None

    item = {
        "source": source,
        "title": clean_text(title)[:400] or "Без заголовка",
        "url": url,
        "text": clean_text(text)[:1500],
        "date": clean_text(date)[:100],
        "query": query,
    }

    item["score"], item["level"], item["signals"] = score_lead(item)

    return item


# ============================================================
# SEARCH QUERIES
# ============================================================

def build_queries():
    queries = list(BUY_INTENT)

    for brand in BRANDS:
        queries.append(f'"ищу {brand}"')
        queries.append(f'"где купить {brand}"')
        queries.append(f'"куплю {brand} винтаж')

    for clothing in CLOTHING:
        queries.append(f'"ищу {clothing}" винтаж')
        queries.append(f'"где купить {clothing}"')

    for style in STYLES:
        queries.append(f'"ищу" "{style}" одежда')
        queries.append(f'"где купить" "{style}"')

    for city in CITIES:
        queries.append(f'"ищу винтажную одежду" "{city}"')
        queries.append(f'"винтажный магазин" "{city}"')

    # Search public pages indexed from marketplaces and social sites.
    for domain in MARKETPLACES + SOCIAL_SITES:
        queries.append(f'site:{domain} "ищу винтажную одежду"')
        queries.append(f'site:{domain} "где купить винтаж"')
        queries.append(f'site:{domain} "ищу Carhartt"')

    # Preserve order and remove duplicates.
    return list(dict.fromkeys(queries))


# ============================================================
# BING RSS SEARCH
# ============================================================

def bing_search(query):
    url = (
        "https://www.bing.com/search?format=rss&count=10&q="
        + urllib.parse.quote(query)
    )

    status, body = fetch(
        url,
        headers={"Accept": "application/rss+xml, application/xml, text/xml"},
    )

    if status != 200 or not body:
        log(f"Bing unavailable: HTTP {status}")
        return []

    try:
        root = ET.fromstring(body)
    except Exception:
        log("Bing returned a non-RSS response.")
        return []

    results = []

    for node in root.findall(".//item")[:10]:
        title = node.findtext("title", "")
        link = node.findtext("link", "")
        description = node.findtext("description", "")
        pub_date = node.findtext("pubDate", "")

        item = create_item(
            "Bing web search",
            title,
            link,
            description,
            pub_date,
            query,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# DUCKDUCKGO SEARCH
# ============================================================

def duckduckgo_search(query):
    url = (
        "https://html.duckduckgo.com/html/?q="
        + urllib.parse.quote(query)
    )

    status, body = fetch(url)

    if status != 200 or not body:
        log(f"DuckDuckGo unavailable/challenge: HTTP {status}")
        return []

    if "anomaly.js" in body.lower():
        log("DuckDuckGo presented an automated-request challenge.")
        return []

    results = []

    # Extract individual result links conservatively.
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(body):
        url_found = html.unescape(match.group(1))
        title = clean_text(match.group(2))

        try:
            parsed = urllib.parse.urlsplit(url_found)
            params = urllib.parse.parse_qs(parsed.query)

            if "uddg" in params:
                url_found = params["uddg"][0]
        except Exception:
            pass

        item = create_item(
            "DuckDuckGo web search",
            title,
            url_found,
            "",
            "",
            query,
        )

        if item:
            results.append(item)

        if len(results) >= 10:
            break

    return results


# ============================================================
# OPTIONAL YOUTUBE API
# ============================================================

def youtube_search(query):
    if not YOUTUBE_API_KEY:
        return []

    params = urllib.parse.urlencode({
        "part": "snippet",
        "type": "video",
        "maxResults": 10,
        "q": query,
        "key": YOUTUBE_API_KEY,
        "regionCode": "RU",
        "relevanceLanguage": "ru",
        "order": "date",
    })

    url = "https://www.googleapis.com/youtube/v3/search?" + params

    status, body = fetch(url)

    if status != 200:
        log(f"YouTube API unavailable: HTTP {status}")
        return []

    try:
        data = json.loads(body)
    except Exception:
        return []

    results = []

    for row in data.get("items", []):
        snippet = row.get("snippet", {})
        video_id = row.get("id", {}).get("videoId")

        if not video_id:
            continue

        item = create_item(
            "YouTube API",
            snippet.get("title", ""),
            f"https://www.youtube.com/watch?v={video_id}",
            snippet.get("description", ""),
            snippet.get("publishedAt", ""),
            query,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# OPTIONAL VK API
# ============================================================

def vk_search(query):
    if not VK_TOKEN:
        return []

    params = urllib.parse.urlencode({
        "q": query,
        "count": 20,
        "access_token": VK_TOKEN,
        "v": "5.199",
    })

    url = "https://api.vk.com/method/newsfeed.search?" + params

    status, body = fetch(url)

    if status != 200:
        log(f"VK API unavailable: HTTP {status}")
        return []

    try:
        data = json.loads(body)
    except Exception:
        return []

    if "error" in data:
        log("VK API error: " + str(data["error"].get("error_msg", "unknown")))
        return []

    results = []

    for row in data.get("response", {}).get("items", []):
        owner = row.get("owner_id")
        post_id = row.get("id")

        if owner is None or post_id is None:
            continue

        text = row.get("text", "")

        item = create_item(
            "VK API",
            text[:120] or "VK post",
            f"https://vk.com/wall{owner}_{post_id}",
            text,
            "",
            query,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# REDDIT PUBLIC SEARCH
# ============================================================

def reddit_search(query):
    url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode({
        "q": query,
        "sort": "new",
        "limit": 10,
        "type": "link",
    })

    status, body = fetch(
        url,
        headers={"User-Agent": "VintageClientFinder/1.0 public search"},
    )

    if status != 200:
        log(f"Reddit search unavailable: HTTP {status}")
        return []

    try:
        data = json.loads(body)
    except Exception:
        return []

    results = []

    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})

        item = create_item(
            "Reddit public search",
            post.get("title", ""),
            "https://www.reddit.com" + post.get("permalink", ""),
            post.get("selftext", ""),
            "",
            query,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# PUBLIC TELEGRAM CHANNEL PREVIEWS
# ============================================================

def telegram_channel_search(channel):
    # This reads public channel previews, not Telegram's global search.
    url = "https://t.me/s/" + urllib.parse.quote(channel)
    status, body = fetch(url)

    if status != 200 or not body:
        log(f"Public Telegram channel unavailable: @{channel}")
        return []

    results = []

    # Parse post identifiers and nearby message text.
    post_ids = re.findall(
        r'data-post="([^"]+)"',
        body,
    )

    for post_id in dict.fromkeys(post_ids):
        post_url = "https://t.me/" + post_id
        escaped_id = re.escape(post_id)

        match = re.search(
            escaped_id + r'[\s\S]{0,5000}?tgme_widget_message_text[^>]*>([\s\S]*?)</div>',
            body,
        )

        text = clean_text(match.group(1)) if match else ""

        item = create_item(
            f"Telegram public channel @{channel}",
            text[:120] or "Public Telegram post",
            post_url,
            text,
            "",
            "@" + channel,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# EXTRA RSS FEEDS
# ============================================================

def rss_search(feed_url):
    status, body = fetch(
        feed_url,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml"},
    )

    if status != 200 or not body:
        log(f"RSS unavailable: HTTP {status} — {feed_url}")
        return []

    try:
        root = ET.fromstring(body)
    except Exception:
        log(f"Invalid RSS/XML: {feed_url}")
        return []

    results = []

    # RSS 2.0
    for node in root.findall(".//item")[:100]:
        item = create_item(
            "Custom RSS",
            node.findtext("title", ""),
            node.findtext("link", ""),
            node.findtext("description", ""),
            node.findtext("pubDate", ""),
            feed_url,
        )

        if item:
            results.append(item)

    # Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for node in root.findall(".//atom:entry", ns)[:100]:
        link_node = node.find("atom:link", ns)
        link = link_node.attrib.get("href", "") if link_node is not None else ""

        item = create_item(
            "Custom RSS / Atom",
            node.findtext("atom:title", "", ns),
            link,
            node.findtext("atom:summary", "", ns),
            node.findtext("atom:published", "", ns),
            feed_url,
        )

        if item:
            results.append(item)

    return results


# ============================================================
# TELEGRAM NOTIFICATIONS
# ============================================================

def send_telegram(item):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram credentials missing; alert printed to logs.")
        print(format_message(item))
        return False

    message = format_message(item)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    status, body = fetch(
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=payload,
        method="POST",
        timeout=20,
    )

    if status != 200:
        log(f"Telegram send failed: HTTP {status}")
        return False

    try:
        return bool(json.loads(body).get("ok"))
    except Exception:
        return False


def format_message(item):
    signals = "; ".join(item.get("signals", [])) or "Недостаточно сигналов"

    return (
        "🧥 VINTAGE CLIENT FINDER\n\n"
        f"Потенциал: {item['level']}\n"
        f"Балл: {item['score']}/100\n"
        f"Источник: {item['source']}\n"
        f"Заголовок: {item['title']}\n\n"
        f"Текст: {item.get('text', '')[:900] or 'Описание не найдено'}\n\n"
        f"Сигналы: {signals}\n"
        f"Дата: {item.get('date', '') or 'не указана'}\n"
        f"Запрос: {item.get('query', '')}\n\n"
        f"Ссылка: {item['url']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    log("=== VINTAGE CLIENT FINDER START ===")

    seen = load_seen()
    queries = build_queries()

    # Rotate query batches between scheduled runs so that the whole query bank
    # is searched over time rather than repeating only the first terms.
    state_path = BASE_DIR / "search_state.json"

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        state = {}

    cursor = int(state.get("cursor", 0)) % len(queries)

    batch = [
        queries[(cursor + i) % len(queries)]
        for i in range(min(MAX_QUERIES, len(queries)))
    ]

    state["cursor"] = (cursor + len(batch)) % len(queries)

    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log(f"Query bank: {len(queries)}")
    log(f"Queries this run: {len(batch)}")

    results = []

    for index, query in enumerate(batch, start=1):
        log(f"Searching {index}/{len(batch)}: {query}")

        results.extend(bing_search(query))
        results.extend(duckduckgo_search(query))

        # Optional API integrations use a subset to control API quotas.
        if index <= 8:
            results.extend(youtube_search(query))
            results.extend(vk_search(query))

        if index <= 5:
            results.extend(reddit_search(query))

        if REQUEST_DELAY:
            time.sleep(REQUEST_DELAY)

    for feed in EXTRA_RSS:
        results.extend(rss_search(feed))

    for channel in TELEGRAM_CHANNELS:
        results.extend(telegram_channel_search(channel))

    # Prefer the strongest result when the same URL is found by several sources.
    unique = {}

    for item in results:
        key = fingerprint(item)

        if key not in unique or item["score"] > unique[key]["score"]:
            unique[key] = item

    ranked = sorted(
        unique.items(),
        key=lambda pair: pair[1]["score"],
        reverse=True,
    )

    log(f"Raw results: {len(results)}")
    log(f"Unique results: {len(unique)}")

    sent = 0

    for key, item in ranked:
        if key in seen:
            continue

        # Skip very weak matches to avoid flooding the Telegram chat.
        if item["score"] < 20:
            seen[key] = {
                "url": item["url"],
                "score": item["score"],
                "seen_at": datetime.now(timezone.utc).isoformat(),
            }
            continue

        log(
            f"LEAD score={item['score']} "
            f"source={item['source']} "
            f"title={item['title'][:100]} "
            f"url={item['url']}"
        )

        delivered = send_telegram(item)

        # In console-only mode, record results so logs do not repeat forever.
        if delivered or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
            seen[key] = {
                "url": item["url"],
                "score": item["score"],
                "source": item["source"],
                "seen_at": datetime.now(timezone.utc).isoformat(),
            }
            sent += 1

        if sent >= MAX_ALERTS:
            log("Reached MAX_ALERTS_PER_RUN limit.")
            break

        time.sleep(0.2)

    save_seen(seen)

    log(f"New leads processed: {sent}")
    log(f"Stored fingerprints: {len(seen)}")
    log("=== RUN FINISHED ===")


if __name__ == "__main__":
    main()
