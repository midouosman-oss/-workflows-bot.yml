#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import html
import hashlib
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from html.parser import HTMLParser

# ==========================================
# CONFIG
# ==========================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SEEN_FILE = Path(os.getenv("SEEN_FILE", "seen.json"))
MAX_RESULTS_PER_QUERY = 15

SEARCH_TERMS = [
    '"ищу секонд хенд"',
    '"ищу секонд-хенд"',
    '"ищу винтажную одежду"',
    '"ищу винтаж"',
    '"где купить винтаж"',
    '"посоветуйте секонд хенд"',
    '"ищу одежду бу"',
    '"где найти винтажную одежду"',
    '"ищу винтажный магазин"',
    '"ищу винтажную куртку"',
    '"ищу винтажные джинсы"',
    '"looking for vintage clothes"',
    '"looking for second hand clothes"',
    '"recommend a thrift store"',
]

SITES = [
    "site:threads.com",
    "site:threads.net",
]

CLOTHING_RE = re.compile(
    r"секонд[\s-]?хенд|second[\s-]?hand|"
    r"винтаж\w*|vintage|thrift|"
    r"одежд\w*|clothes|clothing|"
    r"куртк\w*|джинс\w*|юбк\w*|"
    r"пальто|плать\w*|брюк\w*|"
    r"рубашк\w*|сумк\w*|обув\w*|"
    r"барахолк\w*|комиссионк\w*",
    re.IGNORECASE,
)

INTENT_RE = re.compile(
    r"ищу|ищем|ищется|подскаж\w*|посовет\w*|"
    r"где\s+(можно\s+)?(купить|найти|взять)|"
    r"кто\s+(знает|может)|не\s+знаете|"
    r"нужн\w*|хочу\s+купить|"
    r"looking\s+for|anyone\s+know|"
    r"recommend\w*|where\s+(can|to)|"
    r"ищу\s+магазин|"
    r"где\s+одеваться",
    re.IGNORECASE,
)

# ==========================================
# HTML PARSER
# ==========================================

class SearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")

        if tag == "a" and "result__a" in classes:
            self.current = {
                "url": attrs.get("href", ""),
                "title": "",
                "snippet": "",
            }
            self.capture = "title"

        elif tag in ("a", "div", "td") and (
            "result__snippet" in classes
        ):
            if self.results:
                self.capture = "snippet"

    def handle_data(self, data):
        text = data.strip()
        if not text or not self.results and not self.current:
            return

        if self.current and self.capture == "title":
            self.current["title"] += " " + text

        elif self.results and self.capture == "snippet":
            self.results[-1]["snippet"] += " " + text

    def handle_endtag(self, tag):
        if tag == "a" and self.current:
            result = self.current
            result["title"] = result["title"].strip()
            result["snippet"] = result["snippet"].strip()
            self.results.append(result)
            self.current = None
            self.capture = None


# ==========================================
# HTTP
# ==========================================

def get_page(url, timeout=25):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


# ==========================================
# DUCKDUCKGO SEARCH
# ==========================================

def normalize_result_url(url):
    url = html.unescape(url.strip())

    if url.startswith("//"):
        url = "https:" + url

    if "duckduckgo.com/l/?" in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        url = params.get("uddg", [url])[0]

    return url


def is_threads_url(url):
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return (
            host == "threads.com"
            or host.endswith(".threads.com")
            or host == "threads.net"
            or host.endswith(".threads.net")
        )
    except Exception:
        return False


def search_web(term, site):
    query = f"{site} {term}"
    url = (
        "https://html.duckduckgo.com/html/?"
        + urllib.parse.urlencode({"q": query})
    )

    print(f"Searching web: {query}")

    page = get_page(url)
    parser = SearchParser()
    parser.feed(page)

    results = []

    for item in parser.results[:MAX_RESULTS_PER_QUERY]:
        link = normalize_result_url(item["url"])
        title = html.unescape(item["title"]).strip()
        snippet = html.unescape(item["snippet"]).strip()

        if not is_threads_url(link):
            continue

        text = f"{title}\n{snippet}".strip()

        if not text:
            continue

        if not CLOTHING_RE.search(text):
            continue

        if not INTENT_RE.search(text):
            continue

        post_id = hashlib.sha256(
            link.encode("utf-8")
        ).hexdigest()[:24]

        results.append({
            "id": post_id,
            "url": link,
            "text": text,
        })

    print(f"Search results accepted: {len(results)}")
    return results


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Telegram secrets are not configured.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message[:4000],
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        if result.get("ok"):
            return True

        print("Telegram error:", result)
        return False

    except Exception as error:
        print("Telegram send error:", error)
        return False


# ==========================================
# STATE
# ==========================================

def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        with SEEN_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return set(data.get("ids", []))

        if isinstance(data, list):
            return set(data)

    except Exception as error:
        print("Could not read seen file:", error)

    return set()


def save_seen(ids):
    state = {"ids": list(ids)[-10000:]}
    temporary = SEEN_FILE.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)

    temporary.replace(SEEN_FILE)


# ==========================================
# MAIN
# ==========================================

def run_once():
    seen = load_seen()
    found = {}

    for term in SEARCH_TERMS:
        for site in SITES:
            try:
                posts = search_web(term, site)

                for post in posts:
                    found[post["id"]] = post

            except Exception as error:
                print(
                    f"Search failed for {site} {term}: {error}"
                )

            time.sleep(2)

    if not found:
        print(
            "No matching public Threads posts found. "
            "This does not prove that no matching posts exist."
        )
        return

    new_posts = [
        post for post_id, post in found.items()
        if post_id not in seen
    ]

    sent = 0

    for post in new_posts:
        message = (
            "🧥 Найдена публикация о винтаже / секонд-хенде\n\n"
            f"{post['text']}\n\n"
            f"Источник: {post['url']}"
        )

        if send_telegram(message):
            seen.add(post["id"])
            sent += 1

        time.sleep(1)

    save_seen(seen)

    print(
        f"Results: {len(found)} | "
        f"New: {len(new_posts)} | "
        f"Sent: {sent}"
    )


if __name__ == "__main__":
    print("Vintage Monitor started")
    run_once()
