#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VINTAGE CLIENT FINDER
Поиск публичных публикаций с потенциальными покупателями винтажной одежды.

Источники:
- DuckDuckGo HTML
- Bing RSS
- YouTube Data API
- VK API
- Reddit public search
- Публичные Telegram-каналы
- Дополнительные RSS

Threads API не используется.
"""

import os
import re
import json
import time
import html
import hashlib
import logging
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime, timezone


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN")
    or os.getenv("TG_TOKEN")
    or ""
).strip()

TELEGRAM_CHAT_ID = (
    os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("TG_CHAT")
    or ""
).strip()

VK_TOKEN = os.getenv("VK_TOKEN", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

SEEN_FILE = Path("seen.json")
STATE_FILE = Path("search_state.json")
LOG_FILE = Path("monitor.log")

MAX_QUERIES = int(os.getenv("MAX_QUERIES", "35"))
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "15"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "1.2"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "35"))

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_SEEN_ITEMS = int(os.getenv("MAX_SEEN_ITEMS", "12000"))
MAX_RESULTS_PER_QUERY = int(os.getenv("MAX_RESULTS_PER_QUERY", "15"))

TELEGRAM_CHANNELS = [
    value.strip().lstrip("@")
    for value in os.getenv("TELEGRAM_CHANNELS", "").split(",")
    if value.strip()
]

EXTRA_RSS = [
    value.strip()
    for value in os.getenv("EXTRA_RSS", "").split(",")
    if value.strip()
]

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)

log = logging.info


# ============================================================
# SEARCH QUERIES
# ============================================================

SEARCH_QUERIES = [
    # Русский: прямые запросы покупателей
    '"ищу винтажную одежду"',
    '"ищу винтаж"',
    '"где купить винтажную одежду"',
    '"где найти винтажную одежду"',
    '"посоветуйте винтажный магазин"',
    '"ищу винтажную куртку"',
    '"ищу кожаную винтажную куртку"',
    '"ищу винтажную джинсовку"',
    '"ищу винтажные джинсы"',
    '"ищу винтажные брюки"',
    '"ищу винтажную юбку"',
    '"ищу винтажное платье"',
    '"ищу винтажную рубашку"',
    '"ищу винтажный свитер"',
    '"ищу винтажную сумку"',
    '"ищу одежду second hand"',
    '"ищу секонд хенд"',
    '"где купить секонд хенд"',
    '"ищу одежду из 90-х"',
    '"ищу одежду 2000-х"',
    '"ищу одежду Y2K"',
    '"куплю винтажную одежду"',
    '"куплю винтажную куртку"',
    '"куплю старую кожаную куртку"',
    '"посоветуйте секонд хенд"',
    '"где найти одежду Y2K"',
    '"ищу одежду в стиле гранж"',
    '"ищу одежду в стиле ретро"',

    # Английский: прямые запросы
    '"looking for vintage clothes"',
    '"looking for vintage clothing"',
    '"where can I buy vintage clothes"',
    '"where to find vintage clothing"',
    '"recommend a vintage store"',
    '"looking for a vintage jacket"',
    '"looking for a vintage leather jacket"',
    '"looking for vintage jeans"',
    '"looking for vintage denim"',
    '"looking for a vintage dress"',
    '"looking for a vintage skirt"',
    '"looking for a vintage shirt"',
    '"looking for a vintage bag"',
    '"looking for second hand clothes"',
    '"where to buy second hand clothes"',
    '"looking for Y2K clothes"',
    '"looking for 90s clothing"',
    '"looking for retro clothing"',
    '"looking for thrift stores"',
    '"recommend a thrift store"',
    '"where can I find thrift stores"',
    '"looking for vintage streetwear"',
    '"looking for vintage designer clothing"',
    '"looking for old school streetwear"',
    '"looking for a used leather jacket"',
    '"anyone selling vintage clothes"',
    '"does anyone know a vintage shop"',
    '"need recommendations for vintage stores"',

    # Намерение купить
    '"want to buy vintage clothes"',
    '"need a vintage jacket"',
    '"trying to find vintage clothing"',
    '"any recommendations for secondhand clothing"',
    '"looking for affordable vintage clothes"',
    '"where to shop vintage"',
    '"looking for vintage Levi\'s"',
    '"looking for vintage Carhartt"',
    '"looking for vintage Nike"',
    '"looking for vintage Adidas"',
    '"looking for vintage Ralph Lauren"',
    '"looking for vintage military jacket"',
    '"looking for vintage workwear"',

    # Поиск по публичным площадкам
    'site:threads.com "looking for vintage"',
    'site:threads.net "looking for vintage"',
    'site:threads.com "ищу винтаж"',
    'site:threads.net "ищу винтаж"',
    'site:reddit.com "looking for vintage clothes"',
    'site:reddit.com "vintage store recommendations"',
    'site:reddit.com "looking for a vintage jacket"',
    'site:reddit.com "where to buy vintage clothing"',
    'site:avito.ru "ищу винтажную одежду"',
    'site:avito.ru "куплю винтажную куртку"',
    'site:youla.ru "ищу винтажную одежду"',
    'site:youla.ru "куплю винтажную куртку"',
    'site:youtube.com/shorts "ищу винтаж"',
    'site:youtube.com/shorts "looking for vintage clothes"',
]


# ============================================================
# SCORING
# ============================================================

BUYING_PHRASES = [
    "ищу", "ищем", "нужен", "нужна", "нужно", "нужны",
    "хочу купить", "куплю", "купить", "где купить",
    "где найти", "посоветуйте", "порекомендуйте",
    "кто знает", "кто продает", "кто продаёт", "где взять",
    "подскажите магазин", "ищу магазин",
    "looking for", "where can i buy", "where to buy",
    "where can i find", "need a", "need some",
    "want to buy", "trying to find", "any recommendations",
    "recommend a", "does anyone know", "anyone selling",
    "where to shop", "looking to buy", "can anyone recommend",
    "i need", "i want",
]

CLOTHING_TERMS = [
    "винтаж", "винтажный", "винтажная", "винтажные",
    "vintage", "second hand", "secondhand", "thrift",
    "thrifting", "секонд", "секонд-хенд", "секонд хенд",
    "ретро", "retro", "y2k", "90s", "90's", "2000s",
    "2000's", "streetwear", "стритвир", "гранж", "grunge",
    "деним", "denim", "джинсов", "джинсы", "jeans",
    "джинсовка", "куртк", "jacket", "coat", "пальто",
    "кожан", "leather", "рубашк", "shirt", "плать",
    "dress", "юбк", "skirt", "брюк", "trousers", "pants",
    "свитер", "sweater", "худи", "hoodie", "футболк",
    "t-shirt", "tshirt", "сумк", "bag", "кардиган",
    "cardigan", "workwear", "military jacket", "carhartt",
    "levi's", "levis", "nike", "adidas", "ralph lauren",
    "tommy hilfiger", "stone island", "diesel",
    "helmut lang", "archive fashion", "архивная одежда",
]

SELLING_ONLY_PHRASES = [
    "продаю", "продам", "продаётся", "продается",
    "available now", "for sale", "dm to buy", "shop now",
    "new collection", "link in bio", "подписывайтесь",
    "подпишись", "мой магазин", "наш магазин",
]

SPAM_PHRASES = [
    "заработок без вложений", "криптовалюта", "казино",
    "ставки на спорт", "розыгрыш айфона", "giveaway",
    "free crypto", "casino", "betting",
]


def contains_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def score_item(item):
    """
    Оценивает содержимое самой публикации.
    Поисковый запрос не влияет на score, чтобы не создавать
    ложные совпадения из-за слов 'ищу' в поисковой фразе.
    """
    title = str(item.get("title", "") or "")
    body = str(item.get("text", "") or "")

    text = html.unescape(f"{title} {body}").lower()
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return 0, ["Пустой текст"]

    score = 0
    reasons = []

    buying_matches = [
        phrase for phrase in BUYING_PHRASES
        if phrase in text
    ]

    clothing_matches = [
        phrase for phrase in CLOTHING_TERMS
        if phrase in text
    ]

    if buying_matches:
        score += 35
        reasons.append("Есть намерение найти или купить")

    if clothing_matches:
        score += 30
        reasons.append("Упоминается одежда или винтаж")

    if buying_matches and clothing_matches:
        score += 20
        reasons.append("Совпадают намерение и категория")

    specific_items = [
        "куртк", "jacket", "джинс", "jeans", "пальто",
        "coat", "плать", "dress", "сумк", "bag",
        "кожан", "leather", "юбк", "skirt", "рубашк",
        "shirt", "carhartt", "levi",
    ]

    if contains_any(text, specific_items):
        score += 10
        reasons.append("Указана конкретная вещь или бренд")

    if contains_any(text, SELLING_ONLY_PHRASES) and not buying_matches:
        score -= 25
        reasons.append("Похоже на объявление продавца")

    if contains_any(text, SPAM_PHRASES):
        score -= 50
        reasons.append("Возможный спам")

    if not buying_matches:
        score = min(score, 25)

    return max(0, min(score, 100)), reasons


# ============================================================
# FILE STATE
# ============================================================

def load_json(path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
    except (OSError, ValueError, TypeError) as exc:
        log(f"Не удалось прочитать {path}: {exc}")

    return default


def save_json(path, data):
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        temporary_path.replace(path)

    except (OSError, TypeError, ValueError) as exc:
        log(f"Не удалось сохранить {path}: {exc}")


seen_data = load_json(SEEN_FILE, {"items": []})

if isinstance(seen_data, list):
    seen_data = {"items": seen_data}

if not isinstance(seen_data, dict):
    seen_data = {"items": []}

seen_items = seen_data.get("items", [])

if not isinstance(seen_items, list):
    seen_items = []

seen_set = set(str(value) for value in seen_items)

state = load_json(STATE_FILE, {"query_cursor": 0})

if not isinstance(state, dict):
    state = {"query_cursor": 0}


def fingerprint(item):
    url = str(item.get("url", "") or "").strip()

    if url:
        normalized = url.split("#", 1)[0].strip().rstrip("/")
    else:
        normalized = (
            str(item.get("title", "")) + "|" +
            str(item.get("text", ""))
        ).strip().lower()

    return hashlib.sha256(
        normalized.encode("utf-8", errors="ignore")
    ).hexdigest()


def save_seen():
    global seen_items, seen_set

    seen_items = seen_items[-MAX_SEEN_ITEMS:]
    seen_set = set(str(value) for value in seen_items)

    save_json(SEEN_FILE, {"items": seen_items})


# ============================================================
# HTTP
# ============================================================

def request(url, headers=None, method="GET", data=None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }

    if headers:
        request_headers.update(headers)

    body = data

    if isinstance(body, dict):
        body = urllib.parse.urlencode(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        headers=request_headers,
        data=body,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            return (
                response.getcode(),
                response.read().decode("utf-8", errors="replace"),
            )

    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(5000).decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            error_body = ""

        log(
            f"HTTP {exc.code} | {url[:160]} | "
            f"{error_body[:500].replace(chr(10), ' ')}"
        )

        return exc.code, error_body

    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        log(f"Ошибка запроса {url[:160]}: {exc}")
        return 0, ""


# ============================================================
# TELEGRAM NOTIFICATIONS
# ============================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram не настроен: проверь TELEGRAM_TOKEN и TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message[:4000],
        "disable_web_page_preview": True,
    }

    status, body = request(
        url,
        headers={"Content-Type": "application/json"},
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
    )

    try:
        result = json.loads(body)
    except (ValueError, TypeError):
        result = {}

    if status == 200 and result.get("ok") is True:
        return True

    log(
        f"Telegram send failed: HTTP {status}; "
        f"{str(result.get('description', body))[:500]}"
    )

    return False


def build_message(item, score, reasons):
    title = html.unescape(
        str(item.get("title", "Без заголовка") or "Без заголовка")
    )

    body = html.unescape(str(item.get("text", "") or "")).strip()
    url = str(item.get("url", "") or "").strip()
    source = str(item.get("source", "Неизвестный источник"))
    query = str(item.get("query", "") or "")

    title = title[:350]
    body = body[:1000]
    query = query[:200]

    lines = [
        "🧥 VINTAGE CLIENT FINDER",
        "",
        f"🎯 Потенциальный клиент: {score}/100",
        f"🔎 Источник: {source}",
        "",
        f"📝 {title}",
    ]

    if body:
        lines.extend(["", body])

    if url:
        lines.extend(["", f"🔗 {url}"])

    if query:
        lines.extend(["", f"🔍 Поиск: {query}"])

    if reasons:
        lines.extend(["", "📊 Совпадения: " + "; ".join(reasons)])

    lines.extend([
        "",
        "🕒 " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    ])

    return "\n".join(lines)


# ============================================================
# RESULT HELPERS
# ============================================================

def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def make_item(title, text, url, source, query=""):
    return {
        "title": clean_text(title)[:500],
        "text": clean_text(text)[:5000],
        "url": str(url or "").strip(),
        "source": source,
        "query": str(query or ""),
    }


def normalize_url(url):
    url = html.unescape(str(url or "")).strip()

    if url.startswith("//"):
        url = "https:" + url

    return url


# ============================================================
# RSS PARSER
# ============================================================

def parse_rss(xml_text, source, query=""):
    results = []

    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        log(f"Ошибка RSS XML ({source}): {exc}")
        return results

    for node in root.iter():
        tag_name = node.tag.split("}")[-1].lower()

        if tag_name not in ("item", "entry"):
            continue

        fields = {}

        for child in list(node):
            child_tag = child.tag.split("}")[-1].lower()
            child_value = "".join(child.itertext()).strip()

            if child_tag not in fields:
                fields[child_tag] = child_value

        title = fields.get("title", "")
        description = (
            fields.get("description", "")
            or fields.get("summary", "")
            or fields.get("content", "")
        )

        link = fields.get("link", "")

        if not link:
            for child in list(node):
                if child.tag.split("}")[-1].lower() == "link":
                    link = child.attrib.get("href", "")
                    if link:
                        break

        if title or description:
            results.append(
                make_item(
                    title=title,
                    text=description,
                    url=normalize_url(link),
                    source=source,
                    query=query,
                )
            )

        if len(results) >= MAX_RESULTS_PER_QUERY:
            break

    return results


# ============================================================
# DUCKDUCKGO HTML SEARCH
# ============================================================

class DuckDuckGoParser(HTMLParser):
    """
    Извлекает заголовок, ссылку и сниппет результата.
    Сниппет привязывается к результату после обработки заголовка.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.capture_title = False
        self.title_depth = 0
        self.capture_snippet = False
        self.snippet_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        href = attrs.get("href", "")

        if tag == "a" and "result__a" in classes:
            self._finish_result()

            self.current = {
                "title": "",
                "url": href,
                "text": "",
            }

            self.capture_title = True
            self.title_depth = 1
            return

        if self.current and tag == "div" and "result__snippet" in classes:
            self.capture_snippet = True
            self.snippet_depth = 1
            return

        if self.capture_title and tag in ("span", "b", "strong"):
            self.title_depth += 1

        if self.capture_snippet and tag in ("div", "span", "b", "strong"):
            self.snippet_depth += 1

    def handle_endtag(self, tag):
        if self.capture_title and tag == "a":
            self.capture_title = False
            self.title_depth = 0

        if self.capture_snippet and tag in ("div", "span", "b", "strong"):
            self.snippet_depth -= 1

            if self.snippet_depth <= 0:
                self.capture_snippet = False
                self.snippet_depth = 0

    def handle_data(self, data):
        if not self.current:
            return

        if self.capture_title:
            self.current["title"] += data

        elif self.capture_snippet:
            self.current["text"] += " " + data

    def _finish_result(self):
        if self.current:
            title = clean_text(self.current.get("title", ""))
            url = self.current.get("url", "")
            text = clean_text(self.current.get("text", ""))

            if title and url:
                self.results.append({
                    "title": title,
                    "url": url,
                    "text": text,
                })

        self.current = None
        self.capture_title = False
        self.capture_snippet = False
        self.title_depth = 0
        self.snippet_depth = 0

    def close(self):
        super().close()
        self._finish_result()


def duckduckgo_search(query):
    url = (
        "https://html.duckduckgo.com/html/?"
        + urllib.parse.urlencode({"q": query})
    )

    status, content = request(
        url,
        headers={
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Referer": "https://duckduckgo.com/",
        },
    )

    if status != 200 or not content:
        log(f"DuckDuckGo unavailable: HTTP {status}")
        return []

    if "anomaly-modal" in content.lower():
        log("DuckDuckGo показал проверку; запрос пропущен")
        return []

    parser = DuckDuckGoParser()

    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:
        log(f"DuckDuckGo parser error: {exc}")
        return []

    results = []

    for entry in parser.results[:MAX_RESULTS_PER_QUERY]:
        result_url = entry.get("url", "")

        if "duckduckgo.com/l/?" in result_url:
            parsed = urllib.parse.urlparse(result_url)
            params = urllib.parse.parse_qs(parsed.query)
            result_url = params.get("uddg", [result_url])[0]

        result_url = normalize_url(result_url)

        if not result_url.startswith(("http://", "https://")):
            continue

        results.append(
            make_item(
                title=entry["title"],
                text=entry["text"],
                url=result_url,
                source="DuckDuckGo Web Search",
                query=query,
            )
        )

    log(f"DuckDuckGo: {len(results)} результатов")
    return results


# ============================================================
# BING RSS SEARCH
# ============================================================

bing_disabled = False


def bing_search(query):
    global bing_disabled

    if bing_disabled:
        return []

    url = (
        "https://www.bing.com/search?"
        + urllib.parse.urlencode({
            "q": query,
            "format": "rss",
            "count": MAX_RESULTS_PER_QUERY,
        })
    )

    status, content = request(
        url,
        headers={
            "Accept": "application/rss+xml,application/xml,text/xml,*/*",
        },
    )

    if status in (202, 403, 429):
        log(f"Bing RSS отключён на этот запуск: HTTP {status}")
        bing_disabled = True
        return []

    if status != 200 or not content:
        return []

    results = parse_rss(content, "Bing RSS", query)
    log(f"Bing RSS: {len(results)} результатов")
    return results


# ============================================================
# YOUTUBE DATA API
# ============================================================

def youtube_search(query):
    if not YOUTUBE_API_KEY:
        return []

    url = (
        "https://www.googleapis.com/youtube/v3/search?"
        + urllib.parse.urlencode({
            "part": "snippet",
            "type": "video",
            "maxResults": min(MAX_RESULTS_PER_QUERY, 50),
            "q": query,
            "key": YOUTUBE_API_KEY,
        })
    )

    status, content = request(url)

    if status != 200:
        log(f"YouTube API: HTTP {status}")
        return []

    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []

    if "error" in data:
        log(f"YouTube API error: {str(data['error'])[:400]}")
        return []

    results = []

    for entry in data.get("items", []):
        snippet = entry.get("snippet", {})
        video_id = entry.get("id", {}).get("videoId", "")

        if not video_id:
            continue

        results.append(
            make_item(
                title=snippet.get("title", ""),
                text=snippet.get("description", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                source="YouTube Data API",
                query=query,
            )
        )

    return results


# ============================================================
# VK API
# ============================================================

def vk_search(query):
    if not VK_TOKEN:
        return []

    url = (
        "https://api.vk.com/method/newsfeed.search?"
        + urllib.parse.urlencode({
            "q": query,
            "count": min(MAX_RESULTS_PER_QUERY, 200),
            "access_token": VK_TOKEN,
            "v": "5.199",
        })
    )

    status, content = request(url)

    if status != 200:
        log(f"VK API: HTTP {status}")
        return []

    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []

    if data.get("error"):
        log("VK API error: " + str(data["error"].get("error_msg", ""))[:300])
        return []

    results = []

    for entry in data.get("response", {}).get("items", []):
        owner_id = entry.get("owner_id")
        post_id = entry.get("id")

        if not owner_id or not post_id:
            continue

        text = entry.get("text", "")

        results.append(
            make_item(
                title=text[:200] or "VK post",
                text=text,
                url=f"https://vk.com/wall{owner_id}_{post_id}",
                source="VK API",
                query=query,
            )
        )

    return results


# ============================================================
# REDDIT PUBLIC SEARCH
# ============================================================

def reddit_search(query):
    url = (
        "https://www.reddit.com/search.json?"
        + urllib.parse.urlencode({
            "q": query,
            "sort": "new",
            "limit": min(MAX_RESULTS_PER_QUERY, 100),
            "type": "link",
        })
    )

    status, content = request(
        url,
        headers={
            "User-Agent": "VintageClientFinder/1.0",
            "Accept": "application/json",
        },
    )

    if status != 200:
        log(f"Reddit search: HTTP {status}")
        return []

    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []

    results = []

    for child in data.get("data", {}).get("children", []):
        entry = child.get("data", {})
        permalink = entry.get("permalink", "")

        if not permalink:
            continue

        results.append(
            make_item(
                title=entry.get("title", ""),
                text=entry.get("selftext", ""),
                url="https://www.reddit.com" + permalink,
                source="Reddit Public Search",
                query=query,
            )
        )

    return results


# ============================================================
# FIXED TELEGRAM PUBLIC CHANNEL PARSER
# ============================================================

class TelegramPreviewParser(HTMLParser):
    """
    Парсер публичного HTML-превью t.me/s/<channel>.

    Ключевое исправление:
    - корректно отслеживается вложенность контейнеров div;
    - текст сообщения собирается только внутри блока текста;
    - permalink берётся из tgme_widget_message_date;
    - сообщение завершается на закрытии внешнего контейнера;
    - сообщения без индивидуальных ссылок не выдаются как отдельные лиды.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.messages = []
        self.current = None

        self.message_depth = 0
        self.capture_text = False
        self.text_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()

        # Начало внешнего контейнера одного Telegram-сообщения.
        if tag == "div" and "tgme_widget_message" in classes:
            if self.current is not None:
                self._finish_message()

            self.current = {
                "text": "",
                "url": "",
            }

            self.message_depth = 1
            self.capture_text = False
            self.text_depth = 0
            return

        if self.current is None:
            return

        # Учитываем вложенность div всего сообщения.
        if tag == "div":
            self.message_depth += 1

        # Telegram указывает индивидуальный permalink на дате сообщения.
        if tag == "a" and "tgme_widget_message_date" in classes:
            href = attrs.get("href", "").strip()

            if href:
                self.current["url"] = href

        # Контейнер текста сообщения.
        if tag == "div" and "tgme_widget_message_text" in classes:
            self.capture_text = True
            self.text_depth = 1
            return

        # Вложенные div внутри блока текста.
        if self.capture_text and tag == "div":
            self.text_depth += 1

    def handle_endtag(self, tag):
        if self.current is None or tag != "div":
            return

        # Уменьшаем глубину блока текста.
        if self.capture_text:
            self.text_depth -= 1

            if self.text_depth <= 0:
                self.capture_text = False
                self.text_depth = 0

        # Уменьшаем глубину контейнера сообщения.
        self.message_depth -= 1

        # Только закрытие внешнего контейнера завершает сообщение.
        if self.message_depth <= 0:
            self._finish_message()

    def handle_data(self, data):
        if self.current is not None and self.capture_text:
            self.current["text"] += " " + data

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

        # Для самозакрывающегося элемента не закрываем внешнее сообщение.
        if tag.lower() == "div":
            self.handle_endtag(tag)

    def _finish_message(self):
        if self.current is None:
            return

        text = clean_text(self.current.get("text", ""))
        url = self.current.get("url", "").strip()

        if text and url:
            if url.startswith("/"):
                url = "https://t.me" + url

            self.messages.append({
                "title": text[:200],
                "text": text,
                "url": url,
            })

        self.current = None
        self.message_depth = 0
        self.capture_text = False
        self.text_depth = 0

    def close(self):
        super().close()
        self._finish_message()


def telegram_channel_search(channel):
    channel = channel.strip().lstrip("@")

    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", channel):
        log(f"Некорректное имя Telegram-канала: {channel}")
        return []

    url = f"https://t.me/s/{urllib.parse.quote(channel)}"

    status, content = request(
        url,
        headers={
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
        },
    )

    if status != 200 or not content:
        log(f"Telegram preview @{channel}: HTTP {status}")
        return []

    parser = TelegramPreviewParser()

    try:
        parser.feed(content)
        parser.close()
    except Exception as exc:
        log(f"Ошибка парсинга Telegram @{channel}: {exc}")
        return []

    results = []
    seen_urls = set()

    for entry in parser.messages:
        message_url = entry.get("url", "").strip()

        if message_url.startswith("/"):
            message_url = "https://t.me" + message_url

        if not message_url.startswith("https://t.me/"):
            continue

        if message_url in seen_urls:
            continue

        seen_urls.add(message_url)

        results.append(
            make_item(
                title=entry["title"],
                text=entry["text"],
                url=message_url,
                source=f"Telegram Public Channel @{channel}",
            )
        )

    log(
        f"Telegram @{channel}: "
        f"{len(results)} сообщений с уникальными ссылками"
    )

    return results


# ============================================================
# EXTRA RSS
# ============================================================

def extra_rss_search():
    results = []

    for feed_url in EXTRA_RSS:
        status, content = request(
            feed_url,
            headers={
                "Accept": (
                    "application/rss+xml,application/atom+xml,"
                    "application/xml,*/*"
                ),
            },
        )

        if status != 200 or not content:
            log(f"Дополнительный RSS недоступен: HTTP {status}")
            continue

        results.extend(
            parse_rss(content, source="Extra RSS")
        )

        time.sleep(REQUEST_DELAY)

    log(f"Дополнительные RSS: {len(results)} результатов")
    return results


# ============================================================
# SEARCH RUNNER
# ============================================================

def collect_search_results(query):
    results = []

    # Поисковые системы.
    results.extend(duckduckgo_search(query))
    time.sleep(REQUEST_DELAY)

    results.extend(bing_search(query))
    time.sleep(REQUEST_DELAY)

    # Источники, требующие ключей.
    if YOUTUBE_API_KEY:
        results.extend(youtube_search(query))
        time.sleep(REQUEST_DELAY)

    if VK_TOKEN:
        results.extend(vk_search(query))
        time.sleep(REQUEST_DELAY)

    # Публичный поиск Reddit.
    results.extend(reddit_search(query))
    time.sleep(REQUEST_DELAY)

    return results


# ============================================================
# MAIN
# ============================================================

def run_once():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "ОШИБКА: добавь TELEGRAM_TOKEN и TELEGRAM_CHAT_ID "
            "в GitHub Secrets."
        )
        return

    if not SEARCH_QUERIES:
        log("Нет поисковых запросов.")
        return

    log("=" * 60)
    log("VINTAGE CLIENT FINDER started")
    log(f"Queries available: {len(SEARCH_QUERIES)}")
    log(f"Minimum score: {MIN_SCORE}")
    log(f"Alert limit: {MAX_ALERTS_PER_RUN}")
    log(f"Seen items: {len(seen_set)}")
    log(f"VK enabled: {bool(VK_TOKEN)}")
    log(f"YouTube enabled: {bool(YOUTUBE_API_KEY)}")
    log(f"Telegram channels: {len(TELEGRAM_CHANNELS)}")
    log(f"Extra RSS feeds: {len(EXTRA_RSS)}")

    cursor = int(state.get("query_cursor", 0) or 0)
    cursor %= len(SEARCH_QUERIES)

    query_count = min(MAX_QUERIES, len(SEARCH_QUERIES))

    queries = [
        SEARCH_QUERIES[(cursor + offset) % len(SEARCH_QUERIES)]
        for offset in range(query_count)
    ]

    next_cursor = (cursor + query_count) % len(SEARCH_QUERIES)

    collected = []

    for index, query in enumerate(queries, start=1):
        log(f"Query {index}/{len(queries)}: {query}")

        try:
            collected.extend(collect_search_results(query))
        except Exception as exc:
            log(f"Ошибка поиска по запросу {query}: {exc}")

        time.sleep(REQUEST_DELAY)

    # Проверяем последние публикации заданных публичных Telegram-каналов.
    for channel in TELEGRAM_CHANNELS:
        try:
            collected.extend(telegram_channel_search(channel))
        except Exception as exc:
            log(f"Ошибка Telegram-канала @{channel}: {exc}")

        time.sleep(REQUEST_DELAY)

    # Дополнительные RSS-источники.
    try:
        collected.extend(extra_rss_search())
    except Exception as exc:
        log(f"Ошибка дополнительных RSS: {exc}")

    log(f"Всего собрано результатов: {len(collected)}")

    # Дедупликация в рамках одного запуска.
    unique_results = []
    batch_fingerprints = set()

    for item in collected:
        fp = fingerprint(item)

        if fp in batch_fingerprints:
            continue

        batch_fingerprints.add(fp)
        unique_results.append(item)

    log(f"После дедупликации: {len(unique_results)}")

    # Отбираем кандидатов по содержимому публикации.
    candidates = []

    for item in unique_results:
        fp = fingerprint(item)

        if fp in seen_set:
            continue

        score, reasons = score_item(item)

        if score < MIN_SCORE:
            continue

        candidates.append({
            "item": item,
            "fingerprint": fp,
            "score": score,
            "reasons": reasons,
        })

    candidates.sort(
        key=lambda candidate: candidate["score"],
        reverse=True,
    )

    log(f"Кандидатов выше порога: {len(candidates)}")

    sent_count = 0

    for candidate in candidates:
        if sent_count >= MAX_ALERTS_PER_RUN:
            log("Достигнут лимит уведомлений за запуск.")
            break

        message = build_message(
            candidate["item"],
            candidate["score"],
            candidate["reasons"],
        )

        if telegram_send(message):
            seen_items.append(candidate["fingerprint"])
            seen_set.add(candidate["fingerprint"])
            sent_count += 1

            log(
                f"Уведомление отправлено: "
                f"score={candidate['score']}; "
                f"source={candidate['item'].get('source', '')}"
            )

            save_seen()
            time.sleep(0.8)

        else:
            log(
                "Отправка не удалась; публикация не помечена "
                "как обработанная."
            )

    # Сохраняем курсор после завершения поискового прохода.
    state["query_cursor"] = next_cursor
    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["last_results_count"] = len(collected)
    state["last_unique_count"] = len(unique_results)
    state["last_candidates_count"] = len(candidates)
    state["last_alerts_sent"] = sent_count

    save_json(STATE_FILE, state)
    save_seen()

    log(
        f"Завершено. Отправлено: {sent_count}; "
        f"следующий курсор: {next_cursor}"
    )
    log("=" * 60)


def main():
    try:
        run_once()
    except KeyboardInterrupt:
        log("Остановка по запросу пользователя.")
    except Exception as exc:
        log(f"Критическая ошибка запуска: {exc}")
        raise


if __name__ == "__main__":
    main()
