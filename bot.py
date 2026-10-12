#!/usr/bin/env python3

import os
import re
import sys
import json
import time
import html
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BOT_NAME = "Vintage Monitor"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SEEN_FILE = Path(os.getenv("SEEN_FILE", "seen.json"))
MAX_SEEN = 5000

SEARCH_TERMS = [
    '"ищу секонд хенд"',
    '"ищу секонд-хенд"',
    '"ищу винтажную одежду"',
    '"куплю винтажную одежду"',
    '"продам винтажную одежду"',
    '"винтажная одежда купить"',
    '"одежда секонд хенд"',
    '"винтажный магазин одежда"',
    '"куплю одежду бу"',
    '"продам одежду бу"',
    '"ищу винтаж"',
    '"ищу одежду vintage"',
    '"second hand clothes Russia"',
    '"vintage clothing Russia"',
]

DOMAINS = [
    "threads.com",
    "threads.net",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

CLOTHING_RE = re.compile(
    r"\b("
    r"винтаж\w*|vintage|"
    r"секонд[\s-]?хенд|second[\s-]?hand|"
    r"одежд\w*|clothes|clothing|"
    r"куртк\w*|пальто|джинс\w*|"
    r"юбк\w*|плать\w*|"
    r"рубашк\w*|брюк\w*|"
    r"обув\w*|сумк\w*|"
    r"thrift|барахолк\w*|"
    r"бу вещ\w*|б/у"
    r")\b",
    re.IGNORECASE,
)

INTENT_RE = re.compile(
    r"\b("
    r"ищу|куплю|продам|продаю|"
    r"купить|продажа|найти|"
    r"посоветуйте|подскажите|"
    r"где купить|где найти|"
    r"нужен|нужна|нужно|"
    r"ищем|отдам|обмен|"
    r"looking for|buy|sell|"
    r"for sale|where to buy|"
    r"second hand|thrift"
    r")\b",
    re.IGNORECASE,
)


def log(message):
    print(message, flush=True)


def load_seen():
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(str(item) for item in data)
    except (OSError, ValueError):
        pass

    return set()


def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)

    items = sorted(seen)[-MAX_SEEN:]

    SEEN_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "ERROR: TELEGRAM_TOKEN или TELEGRAM_CHAT_ID "
            "не настроен в GitHub Secrets."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "VintageMonitor/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok"):
            return True

        log("Telegram API error: " + str(result.get("description")))
        return False

    except Exception as exc:
        log(f"Telegram sending error: {exc}")
        return False


def unwrap_url(url):
    url = html.unescape(url.strip())

    if url.startswith("//"):
        url = "https:" + url

    parsed = urllib.parse.urlparse(url)

    if "duckduckgo.com" in parsed.netloc.lower():
        params = urllib.parse.parse_qs(parsed.query)
        targets = params.get("uddg", [])

        if targets:
            url = targets[0]
            parsed = urllib.parse.urlparse(url)

    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def is_threads_url(url):
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower().split(":")[0]

        if host not in ("threads.com", "www.threads.com",
                        "threads.net", "www.threads.net"):
            return False

        return "/post/" in parsed.path or "/@" in parsed.path

    except Exception:
        return False


class SearchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.current = None
        self.capture_title = False
        self.capture_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        href = attrs.get("href", "")

        if tag == "a" and "result__a" in classes.split():
            if self.current:
                self.results.append(self.current)

            self.current = {
                "url": unwrap_url(href),
                "title": "",
                "snippet": "",
            }
            self.capture_title = True
            self.capture_snippet = False

        elif tag in ("a", "div", "td") and (
            "result__snippet" in classes.split()
        ):
            if self.current:
                self.capture_snippet = True
                self.capture_title = False

    def handle_data(self, data):
        if not self.current:
            return

        text = data.strip()

        if not text:
            return

        if self.capture_title:
            self.current["title"] += " " + text

        elif self.capture_snippet:
            self.current["snippet"] += " " + text

    def handle_endtag(self, tag):
        if tag == "a" and self.capture_title:
            self.capture_title = False

        if tag in ("a", "div", "td") and self.capture_snippet:
            self.capture_snippet = False

    def finish(self):
        if self.current:
            self.results.append(self.current)
            self.current = None

        return self.results


def duckduckgo_search(query):
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({
        "q": query,
        "kl": "ru-ru",
    })

    request = urllib.request.Request(
        url,
        headers=HEADERS,
    )

    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            status = response.status
            page = response.read().decode("utf-8", errors="replace")

        log(f"  Search HTTP status: {status}")
        log(f"  HTML received: {len(page)} characters")

        if "anomaly-modal" in page.lower():
            log("  WARNING: Search engine may be blocking automated requests.")

        parser = SearchParser()
        parser.feed(page)
        results = parser.finish()

        log(f"  Search results parsed: {len(results)}")
        return results

    except Exception as exc:
        log(f"  SEARCH ERROR: {type(exc).__name__}: {exc}")
        return []


def relevant_post(title, snippet):
    text = f"{title} {snippet}"

    if not CLOTHING_RE.search(text):
        return False

    # Поисковый запрос уже тематический.
    # Нам не обязательно требовать слова «ищу»:
    # объявления о продаже тоже представляют интерес.
    return True


def search_all():
    found = {}

    for term in SEARCH_TERMS:
        for domain in DOMAINS:
            query = f"site:{domain} {term}"

            log(f"\nSearching web: {query}")

            results = duckduckgo_search(query)

            for item in results:
                url = unwrap_url(item.get("url", ""))

                if not is_threads_url(url):
                    continue

                title = " ".join(item.get("title", "").split())
                snippet = " ".join(item.get("snippet", "").split())

                if not relevant_post(title, snippet):
                    continue

                found[url] = {
                    "url": url,
                    "title": title or "Публикация Threads",
                    "snippet": snippet,
                    "query": term,
                }

            # Небольшая пауза между запросами.
            time.sleep(2)

    return list(found.values())


def format_message(post):
    title = post["title"][:350]
    snippet = post["snippet"][:500]

    return (
        "🧥 Найдена публикация о винтаже / секонд-хенде\n\n"
        f"📌 {title}\n\n"
        f"{snippet}\n\n"
        f"🔗 {post['url']}"
    )


def main():
    log("=" * 45)
    log(f"{BOT_NAME} started")
    log("Search engine: DuckDuckGo HTML")
    log("Threads API: not used")
    log("=" * 45)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "WARNING: Telegram secrets are missing. "
            "Search can run, but notifications will not be sent."
        )

    seen = load_seen()
    log(f"Previously recorded links: {len(seen)}")

    posts = search_all()

    log("\n" + "=" * 45)
    log(f"Unique matching Threads posts: {len(posts)}")

    new_posts = [post for post in posts if post["url"] not in seen]

    log(f"New posts: {len(new_posts)}")

    sent = 0
    failed = 0

    for post in new_posts:
        log(f"Processing: {post['url']}")

        if telegram_send(format_message(post)):
            sent += 1
            seen.add(post["url"])
            log("  Telegram: SENT")
        else:
            failed += 1
            log("  Telegram: FAILED")

        time.sleep(1)

    save_seen(seen)

    log("\n" + "=" * 45)
    log(f"Search results: {len(posts)}")
    log(f"New posts: {len(new_posts)}")
    log(f"Sent to Telegram: {sent}")
    log(f"Failed notifications: {failed}")
    log("Finished")
    log("=" * 45)


if __name__ == "__main__":
    main()
