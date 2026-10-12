#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VINTAGE MONITOR
Мониторинг публичных публикаций о поиске и покупке одежды в России.
Возможности:
- Поиск по публичным веб-страницам через DuckDuckGo HTML.
- Поиск по Threads через индексируемые публичные страницы.
- Мониторинг указанных публичных Telegram-каналов.
- Поддержка старых и новых публикаций, если источник их показывает.
- Уведомления в Telegram.
- Защита от повторной отправки.
- Сохранение результатов в seen.json.
- Логирование доступности источников.
Переменные окружения:
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
ITEMS
TELEGRAM_CHANNELS
MAX_RESULTS_PER_QUERY
"""
import os
import re
import sys
import json
import time
import html
import hashlib
import logging
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
# ============================================================
# CONFIGURATION
# ============================================================
BOT_NAME = "Vintage Monitor"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
SEEN_FILE = Path("seen.json")
MAX_SEEN = 10000
REQUEST_TIMEOUT = 20
REQUEST_DELAY = 2
MAX_RESULTS_PER_QUERY = int(
    os.getenv("MAX_RESULTS_PER_QUERY", "8")
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
# Ищем публикации, которые могут привести покупателей.
DEFAULT_SEARCH_TERMS = [
    '"ищу винтажную одежду"',
    '"ищу винтаж"',
    '"куплю винтажную одежду"',
    '"где купить винтажную одежду"',
    '"ищу секонд хенд"',
    '"ищу секонд-хенд"',
    '"посоветуйте секонд хенд"',
    '"где купить секонд хенд"',
    '"ищу одежду бу"',
    '"куплю одежду бу"',
    '"ищу одежду vintage"',
    '"винтажные вещи купить"',
    '"ищу винтажный магазин"',
    '"где купить одежду y2k"',
    '"ищу одежду carhartt"',
    '"ищу одежду dickies"',
    '"ищу одежду levi\'s"',
]
CUSTOM_ITEMS = os.getenv("ITEMS", "").strip()
if CUSTOM_ITEMS:
    SEARCH_TERMS = [
        term.strip()
        for term in CUSTOM_ITEMS.split(",")
        if term.strip()
    ]
else:
    SEARCH_TERMS = DEFAULT_SEARCH_TERMS
# Веб-домены проверяются отдельно.
DOMAINS = [
    "threads.com",
    "threads.net",
    "vk.com",
    "reddit.com",
]
# Пример:
# TELEGRAM_CHANNELS="channel_one,channel_two"
TELEGRAM_CHANNELS = [
    item.strip().lstrip("@")
    for item in os.getenv("TELEGRAM_CHANNELS", "").split(",")
    if item.strip()
]
# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(BOT_NAME)
# ============================================================
# HTTP HELPERS
# ============================================================
def http_get(url, headers=None, timeout=REQUEST_TIMEOUT):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/json;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        headers=request_headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return {
                "ok": True,
                "status": response.status,
                "body": body.decode(charset, errors="replace"),
                "url": response.geturl(),
            }
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return {
            "ok": False,
            "status": exc.code,
            "body": body,
            "url": url,
        }
    except Exception as exc:
        log.warning("HTTP request failed: %s", exc)
        return {
            "ok": False,
            "status": 0,
            "body": "",
            "url": url,
        }
# ============================================================
# TELEGRAM
# ============================================================
def telegram_api(method, payload):
    if not TELEGRAM_TOKEN:
        log.error("TELEGRAM_TOKEN is missing.")
        return None
    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/"
        + method
    )
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )
            if not result.get("ok"):
                log.error(
                    "Telegram API error: %s",
                    result,
                )
                return None
            return result.get("result")
    except Exception as exc:
        log.error("Telegram request failed: %s", exc)
        return None
def telegram_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error(
            "Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID."
        )
        return False
    # Telegram message limit is 4096 characters.
    chunks = [
        text[i:i + 3900]
        for i in range(0, len(text), 3900)
    ]
    success = True
    for chunk in chunks:
        result = telegram_api(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )
        if result is None:
            success = False
        time.sleep(0.4)
    return success
# ============================================================
# SEEN DATABASE
# ============================================================
def load_seen():
    if not SEEN_FILE.exists():
        return {}
    try:
        with SEEN_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning("Cannot read seen database: %s", exc)
    return {}
def save_seen(seen):
    # Keep the latest MAX_SEEN entries.
    if len(seen) > MAX_SEEN:
        ordered = sorted(
            seen.items(),
            key=lambda item: item[1].get("first_seen", ""),
        )
        seen = dict(ordered[-MAX_SEEN:])
    temp_file = SEEN_FILE.with_suffix(".tmp")
    with temp_file.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            seen,
            file,
            ensure_ascii=False,
            indent=2,
        )
    temp_file.replace(SEEN_FILE)
def normalize_url(url):
    url = html.unescape(url.strip())
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    # Remove common tracking parameters.
    query = urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
    )
    query = [
        (key, value)
        for key, value in query
        if not key.lower().startswith("utm_")
        and key.lower() not in {
            "fbclid",
            "gclid",
            "ref",
        }
    ]
    normalized_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            normalized_query,
            "",
        )
    )
def item_id(item):
    value = normalize_url(item.get("url", ""))
    if not value:
        value = (
            item.get("source", "")
            + "|"
            + item.get("title", "")
            + "|"
            + item.get("snippet", "")
        )
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()
# ============================================================
# DUCKDUCKGO SEARCH PARSER
# ============================================================
class SearchParser(HTMLParser):
    """
    Parses common DuckDuckGo HTML result markup.
    Search engine markup may change. Challenge pages, CAPTCHA,
    or HTTP 202 responses are treated as unavailable results.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.capture_title = False
        self.capture_snippet = False
        self.depth = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if (
            tag == "a"
            and "result__a" in classes.split()
        ):
            href = attrs.get("href", "")
            if href:
                self.current = {
                    "url": href,
                    "title": "",
                    "snippet": "",
                }
                self.capture_title = True
                self.capture_snippet = False
        elif self.current and tag in ("div", "a"):
            if "result__snippet" in classes.split():
                self.capture_snippet = True
        if self.capture_snippet:
            self.depth += 1
    def handle_endtag(self, tag):
        if self.capture_title and tag == "a":
            self.capture_title = False
        if self.capture_snippet and tag == "div":
            self.depth -= 1
            if self.depth <= 0:
                self.capture_snippet = False
                self.depth = 0
        if (
            self.current
            and not self.capture_title
            and not self.capture_snippet
        ):
            if self.current.get("title"):
                self.results.append(self.current)
            self.current = None
    def handle_data(self, data):
        if not self.current:
            return
        value = data.strip()
        if not value:
            return
        if self.capture_title:
            self.current["title"] += value + " "
        elif self.capture_snippet:
            self.current["snippet"] += value + " "
def is_search_challenge(result):
    body = result.get("body", "").lower()
    markers = [
        "anomaly-modal",
        "bots use duckduckgo",
        "automated requests",
        "captcha",
        "select all squares",
    ]
    return any(marker in body for marker in markers)
def duckduckgo_search(query):
    encoded = urllib.parse.urlencode(
        {
            "q": query,
            "kl": "ru-ru",
        }
    )
    url = (
        "https://html.duckduckgo.com/html/?"
        + encoded
    )
    response = http_get(url)
    if not response["ok"]:
        log.warning(
            "Search unavailable: HTTP %s",
            response["status"],
        )
        return []
    if response["status"] == 202:
        log.warning(
            "Search returned HTTP 202; "
            "possible automated-request challenge."
        )
        return []
    if is_search_challenge(response):
        log.warning(
            "Search challenge detected; skipping."
        )
        return []
    parser = SearchParser()
    try:
        parser.feed(response["body"])
    except Exception as exc:
        log.warning("Cannot parse search HTML: %s", exc)
        return []
    results = []
    for row in parser.results[:MAX_RESULTS_PER_QUERY]:
        url = row.get("url", "").strip()
        # DuckDuckGo may wrap result URLs in a redirect.
        parsed = urllib.parse.urlparse(url)
        if (
            "duckduckgo.com" in parsed.netloc
            and parsed.path.startswith("/l/")
        ):
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("uddg", [])
            if target:
                url = urllib.parse.unquote(target[0])
        url = normalize_url(url)
        if not url:
            continue
        results.append({
            "source": "Web search",
            "url": url,
            "title": row.get("title", "").strip(),
            "snippet": row.get("snippet", "").strip(),
            "query": query,
        })
    log.info(
        "Search results parsed: %d",
        len(results),
    )
    return results
# ============================================================
# SEARCH QUERY BUILDER
# ============================================================
def build_queries():
    queries = []
    for term in SEARCH_TERMS:
        queries.append(term)
        for domain in DOMAINS:
            queries.append(
                "site:"
                + domain
                + " "
                + term
            )
    # Deduplicate while preserving order.
    return list(dict.fromkeys(queries))
# ============================================================
# PUBLIC TELEGRAM CHANNEL MONITOR
# ============================================================
class TelegramPreviewParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.messages = []
        self.current = None
        self.capture = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        classes = classes.split()
        if (
            tag == "div"
            and "tgme_widget_message" in classes
        ):
            self.current = {
                "url": "",
                "text": "",
                "date": "",
            }
        if not self.current:
            return
        if (
            tag == "a"
            and "tgme_widget_message_date" in classes
        ):
            self.current["url"] = attrs.get("href", "")
        if (
            tag == "time"
            and "datetime" in attrs
        ):
            self.current["date"] = attrs["datetime"]
        if (
            tag == "div"
            and "tgme_widget_message_text" in classes
        ):
            self.capture = True
    def handle_endtag(self, tag):
        if (
            self.current
            and tag == "div"
            and self.capture
        ):
            self.capture = False
        if (
            self.current
            and tag == "div"
        ):
            # Keep collecting text until the message container closes.
            pass
    def handle_data(self, data):
        if self.current and data.strip():
            self.current["text"] += data.strip() + " "
def telegram_public_channel_search(channel):
    """
    Reads publicly visible Telegram channel previews.
    This checks specified public channels only. It does not
    search every Telegram channel globally.
    """
    url = "https://t.me/s/" + urllib.parse.quote(channel)
    response = http_get(url)
    if not response["ok"]:
        log.warning(
            "Telegram channel unavailable: %s (HTTP %s)",
            channel,
            response["status"],
        )
        return []
    # Public channel pages may use different markup.
    # Extract message URLs and nearby visible text conservatively.
    body = response["body"]
    matches = re.findall(
        r'href="(https://t\.me/[^"]+/\d+)"',
        body,
    )
    results = []
    seen_urls = set()
    for message_url in matches:
        message_url = html.unescape(message_url)
        if message_url in seen_urls:
            continue
        seen_urls.add(message_url)
        results.append({
            "source": "Telegram: @" + channel,
            "url": message_url,
            "title": "Public Telegram post",
            "snippet": "",
            "query": channel,
        })
    log.info(
        "Telegram channel @%s: %d post links found",
        channel,
        len(results),
    )
    return results
# ============================================================
# RELEVANCE FILTER
# ============================================================
BUY_INTENT_WORDS = [
    "ищу",
    "куплю",
    "купить",
    "где купить",
    "посоветуйте",
    "подскажите",
    "нужен",
    "нужна",
    "нужны",
    "хочу найти",
    "кто знает",
    "ищем",
]
CLOTHING_WORDS = [
    "одежд",
    "винтаж",
    "vintage",
    "секонд",
    "second hand",
    "secondhand",
    "y2k",
    "carhartt",
    "dickies",
    "levi",
    "джинс",
    "куртк",
    "футболк",
    "свитер",
    "рубашк",
    "пальто",
    "брюк",
    "обув",
    "кроссов",
    "вещ",
    "гардероб",
    "streetwear",
    "стритвир",
]
NEGATIVE_WORDS = [
    "вакансия",
    "работа в секонд",
    "оптом от производителя",
    "поставщик оптом",
]
def text_matches(text):
    text = text.lower()
    has_clothing = any(
        word in text
        for word in CLOTHING_WORDS
    )
    has_buy_intent = any(
        word in text
        for word in BUY_INTENT_WORDS
    )
    has_negative = any(
        word in text
        for word in NEGATIVE_WORDS
    )
    return (
        has_clothing
        and has_buy_intent
        and not has_negative
    )
def is_relevant(item):
    text = (
        item.get("title", "")
        + " "
        + item.get("snippet", "")
        + " "
        + item.get("query", "")
    )
    # Search query itself may contain the buying intent.
    # Do not accept solely on the query; require some evidence
    # in the result title/snippet when available.
    result_text = (
        item.get("title", "")
        + " "
        + item.get("snippet", "")
    )
    if result_text.strip():
        if text_matches(result_text):
            return True
    # Some sources return links without snippets.
    # Retain those for manual review only if the query matches.
    query = item.get("query", "").lower()
    return (
        not result_text.strip()
        and any(
            word in query
            for word in (
                "ищу",
                "куплю",
                "где купить",
                "посоветуйте",
            )
        )
    )
# ============================================================
# RESULT FORMATTING
# ============================================================
def format_item(item):
    source = item.get("source", "Unknown")
    title = item.get("title", "").strip()
    snippet = item.get("snippet", "").strip()
    url = item.get("url", "").strip()
    query = item.get("query", "").strip()
    parts = [
        "🧥 VINTAGE MONITOR",
        "",
        "Источник: " + source,
    ]
    if title:
        parts.append("Заголовок: " + title)
    if snippet:
        parts.append("")
        parts.append(snippet)
    if query:
        parts.append("")
        parts.append("Поисковый запрос: " + query)
    parts.extend([
        "",
        "Ссылка: " + url,
    ])
    return "\n".join(parts)
# ============================================================
# SOURCE STATUS
# ============================================================
SOURCE_STATS = {
    "web_search_attempted": 0,
    "web_search_results": 0,
    "telegram_channels_attempted": 0,
    "telegram_channel_results": 0,
    "relevant": 0,
    "sent": 0,
    "duplicates": 0,
}
def send_daily_summary():
    message = (
        "📊 VINTAGE MONITOR — отчёт\n\n"
        "Запросов веб-поиска: "
        + str(SOURCE_STATS["web_search_attempted"])
        + "\nРезультатов веб-поиска: "
        + str(SOURCE_STATS["web_search_results"])
        + "\nПроверено Telegram-каналов: "
        + str(SOURCE_STATS["telegram_channels_attempted"])
        + "\nСсылок из Telegram: "
        + str(SOURCE_STATS["telegram_channel_results"])
        + "\nПодходящих публикаций: "
        + str(SOURCE_STATS["relevant"])
        + "\nОтправлено в Telegram: "
        + str(SOURCE_STATS["sent"])
        + "\nПовторов пропущено: "
        + str(SOURCE_STATS["duplicates"])
        + "\n\n"
        + "Отчёт показывает результаты доступных источников, "
        + "а не полное покрытие интернета."
    )
    telegram_send(message)
# ============================================================
# MAIN SEARCH
# ============================================================
def collect_web_results():
    results = []
    queries = build_queries()
    log.info(
        "Starting web search: %d queries",
        len(queries),
    )
    for index, query in enumerate(queries, start=1):
        log.info(
            "[%d/%d] Query: %s",
            index,
            len(queries),
            query,
        )
        SOURCE_STATS["web_search_attempted"] += 1
        try:
            rows = duckduckgo_search(query)
            results.extend(rows)
            SOURCE_STATS["web_search_results"] += len(rows)
        except Exception:
            log.exception(
                "Search query failed: %s",
                query,
            )
        time.sleep(REQUEST_DELAY)
    return results
def collect_telegram_results():
    results = []
    for channel in TELEGRAM_CHANNELS:
        SOURCE_STATS["telegram_channels_attempted"] += 1
        try:
            rows = telegram_public_channel_search(channel)
            results.extend(rows)
            SOURCE_STATS["telegram_channel_results"] += len(rows)
        except Exception:
            log.exception(
                "Telegram channel check failed: %s",
                channel,
            )
        time.sleep(1)
    return results
def run():
    started = datetime.now(timezone.utc)
    print("=" * 55)
    print("VINTAGE MONITOR")
    print("Public-source monitoring")
    print("Threads API: not used")
    print("Telegram notifications enabled:", bool(TELEGRAM_TOKEN))
    print("=" * 55)
    if not TELEGRAM_TOKEN:
        log.warning(
            "TELEGRAM_TOKEN is missing. "
            "The bot can search but cannot send notifications."
        )
    if not TELEGRAM_CHAT_ID:
        log.warning(
            "TELEGRAM_CHAT_ID is missing."
        )
    seen = load_seen()
    log.info(
        "Previously recorded links: %d",
        len(seen),
    )
    all_results = []
    # Source 1: indexed public web pages.
    all_results.extend(collect_web_results())
    # Source 2: explicitly configured public Telegram channels.
    all_results.extend(collect_telegram_results())
    log.info(
        "Total collected results before filtering: %d",
        len(all_results),
    )
    # Deduplicate by normalized URL.
    unique = {}
    for item in all_results:
        url = normalize_url(item.get("url", ""))
        if not url:
            continue
        item["url"] = url
        if url not in unique:
            unique[url] = item
    log.info(
        "Unique results: %d",
        len(unique),
    )
    new_count = 0
    for item in unique.values():
        if not is_relevant(item):
            continue
        SOURCE_STATS["relevant"] += 1
        key = item_id(item)
        if key in seen:
            SOURCE_STATS["duplicates"] += 1
            continue
        message = format_item(item)
        # Only mark the result as seen after successful delivery.
        delivered = telegram_send(message)
        if delivered:
            now = datetime.now(timezone.utc).isoformat()
            seen[key] = {
                "url": item["url"],
                "source": item.get("source", ""),
                "title": item.get("title", ""),
                "first_seen": now,
            }
            new_count += 1
            SOURCE_STATS["sent"] += 1
            log.info(
                "Sent: %s",
                item["url"],
            )
        else:
            log.warning(
                "Could not send result; will retry later: %s",
                item["url"],
            )
        time.sleep(0.5)
    save_seen(seen)
    elapsed = (
        datetime.now(timezone.utc) - started
    ).total_seconds()
    log.info(
        "Run finished. New notifications: %d; elapsed: %.1f seconds",
        new_count,
        elapsed,
    )
    # Send a summary only when requested.
    if "--summary" in sys.argv:
        send_daily_summary()
if __name__ == "__main__":
    run()
