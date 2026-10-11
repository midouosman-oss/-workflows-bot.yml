#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import html
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# =========================
# CONFIG
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SEEN_FILE = Path(os.getenv("SEEN_FILE", "seen.json"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "900"))

SEARCH_TERMS = [
    "секонд хенд",
    "секонд-хенд",
    "винтажная одежда",
    "ищу винтаж",
    "одежда бу",
    "винтаж купить",
    "винтажный магазин",
    "second hand clothes",
    "vintage clothing",
    "thrift store Russia",
]

# =========================
# FILTERS
# =========================

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


# =========================
# HTTP
# =========================

def get_url(url, timeout=25):
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


# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN или TELEGRAM_CHAT_ID не настроен")
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
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            print("Telegram error:", result)
            return False

        return True

    except Exception as error:
        print(f"Telegram send error: {error}")
        return False


# =========================
# THREADS PUBLIC SEARCH
# =========================

def build_search_url(term):
    query = urllib.parse.urlencode({"q": term})
    return f"https://www.threads.com/search?{query}"


def extract_posts_from_json(data):
    """Ищет объекты публикаций в JSON, если они присутствуют."""

    if isinstance(data, dict):
        code = data.get("code")
        caption = data.get("caption")

        if isinstance(caption, dict):
            text = caption.get("text", "")
        elif isinstance(caption, str):
            text = caption
        else:
            text = ""

        user = data.get("user") or {}

        if not isinstance(user, dict):
            user = {}

        username = (
            user.get("username")
            or data.get("username")
            or "unknown"
        )

        if isinstance(code, str) and text:
            yield {
                "id": code,
                "username": username,
                "text": html.unescape(str(text)).strip(),
                "url": (
                    f"https://www.threads.com/"
                    f"@{username}/post/{code}"
                ),
            }

        for value in data.values():
            yield from extract_posts_from_json(value)

    elif isinstance(data, list):
        for value in data:
            yield from extract_posts_from_json(value)


def extract_posts_from_page(page):
    posts = {}

    # Извлекаем JSON из script-тегов.
    pattern = re.compile(
        r'<script[^>]*type=["\']application/json["\'][^>]*>'
        r"(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(page):
        raw = html.unescape(match.group(1).strip())

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for post in extract_posts_from_json(data):
            posts[post["id"]] = post

    # Если Threads отдаёт ссылки на посты в HTML,
    # пробуем извлечь их вместе с текстом страницы.
    if not posts:
        print(
            "Предупреждение: в HTML не найдено объектов публикаций. "
            "Возможно, Threads изменил страницу поиска."
        )

    return list(posts.values())


def search_threads(term):
    url = build_search_url(term)
    print(f"Searching Threads: {term}")

    page = get_url(url)
    return extract_posts_from_page(page)


# =========================
# FILTER POSTS
# =========================

def is_relevant(post):
    text = post.get("text", "").strip()

    if not text:
        return False

    if not CLOTHING_RE.search(text):
        return False

    if not INTENT_RE.search(text):
        return False

    return True


# =========================
# SEEN POSTS
# =========================

def load_state():
    if not SEEN_FILE.exists():
        return None

    try:
        with SEEN_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

        if isinstance(data, list):
            return {"initialized": True, "ids": data}

    except (OSError, json.JSONDecodeError):
        pass

    return None


def save_state(ids, initialized=True):
    state = {
        "initialized": initialized,
        "ids": list(ids)[-10000:],
    }

    temporary = SEEN_FILE.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)

    temporary.replace(SEEN_FILE)


# =========================
# MAIN
# =========================

def run_once():
    state = load_state()
    first_run = state is None or not state.get("initialized", False)

    seen = set(state.get("ids", [])) if state else set()
    posts_found = {}

    for term in SEARCH_TERMS:
        try:
            posts = search_threads(term)

            for post in posts:
                posts_found[post["id"]] = post

        except Exception as error:
            print(f"Search error for '{term}': {error}")

        time.sleep(2)

    if not posts_found:
        print(
            "No posts extracted. The public Threads search page "
            "may be unavailable or its structure may have changed."
        )
        return

    # Первый запуск: запоминаем старые публикации без уведомлений.
    if first_run:
        save_state(seen | set(posts_found.keys()))
        print(
            f"Initial baseline saved: {len(posts_found)} posts. "
            "No notifications sent."
        )
        return

    new_ids = set(posts_found.keys()) - seen
    relevant_posts = [
        post
        for post_id, post in posts_found.items()
        if post_id in new_ids and is_relevant(post)
    ]

    successfully_sent = set()

    for post in relevant_posts:
        message = (
            "🧥 Новая публикация: секонд-хенд / винтаж\n\n"
            f"Автор: @{post['username']}\n\n"
            f"{post['text']}\n\n"
            f"{post['url']}"
        )

        if send_telegram(message):
            successfully_sent.add(post["id"])

        time.sleep(1)

    # Запоминаем новые ID, чтобы не повторять публикации.
    save_state(seen | set(posts_found.keys()))

    print(
        f"Found: {len(posts_found)} | "
        f"New: {len(new_ids)} | "
        f"Relevant: {len(relevant_posts)} | "
        f"Sent: {len(successfully_sent)}"
    )


def main():
    print("Threads Vintage Monitor started")

    if "--once" in __import__("sys").argv:
        run_once()
        return

    while True:
        try:
            run_once()
        except Exception as error:
            print("Monitor error:", error)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
