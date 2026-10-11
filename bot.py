#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Мониторинг публичных публикаций Threads:
секонд-хенд, винтажная одежда и одежда б/у в России.

Без официального Threads API.
Новые найденные публикации отправляются в Telegram.
Первый запуск только создаёт базу уже найденных публикаций.
"""

import json
import os
import re
import sys
import time
import html
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------
# НАСТРОЙКИ
# --------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SEEN_FILE = Path(os.getenv("SEEN_FILE", "seen.json"))

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "900"))

# Сколько дней хранить ID публикаций
MAX_SEEN = 10000

# Поисковые запросы. Можно дополнять.
SEARCH_TERMS = [
    "секонд хенд",
    "секонд-хенд",
    "винтажная одежда",
    "винтажный магазин",
    "ищу винтаж",
    "одежда бу",
    "винтаж купить",
    "second hand clothes",
    "vintage clothing",
    "vintage clothes",
]

# Ищем публикации в двух вариантах выдачи.
SEARCH_MODES = ["recent", "default"]

# Ограничиваем сообщения тематикой одежды.
TOPIC_RE = re.compile(
    r"секонд[\s-]?хенд|second[\s-]?hand|"
    r"винтаж\w*|vintage|"
    r"одежд\w*|clothes|clothing|"
    r"куртк\w*|джинс\w*|юбк\w*|пальто|"
    r"плать\w*|брюк\w*|рубашк\w*|"
    r"сумк\w*|обув\w*|барахолк\w*|"
    r"комиссионк\w*|thrift",
    re.IGNORECASE,
)

# Ищем посты, где человек что-то ищет или просит рекомендацию.
INTENT_RE = re.compile(
    r"ищу|ищем|ищется|подскаж\w*|посовет\w*|"
    r"где\s+(?:можно\s+)?(?:купить|найти|взять)|"
    r"кто\s+(?:знает|может)|не\s+знаете|"
    r"нужн\w*|хочу\s+купить|"
    r"looking\s+for|anyone\s+know|"
    r"recommend\w*|where\s+(?:can|to)|"
    r"any\s+recommendations|"
    r"ищу\s+магазин|где\s+одеваться",
    re.IGNORECASE,
)

# --------------------------------------------------
# HTTP
# --------------------------------------------------

def get_page(url):
    """
    Запрашивает публичную страницу.
    Threads может менять формат выдачи или ограничивать запросы.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; "
                "ThreadsPublicSearchMonitor/1.0)"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.8",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", errors="replace")


def telegram_send(message):
    """Отправляет сообщение в Telegram."""

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram не настроен. Сообщение:")
        print(message)
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            print("Telegram вернул ошибку:", result)
            return False

        return True

    except Exception as error:
        print(f"Ошибка Telegram: {error}", file=sys.stderr)
        return False


# --------------------------------------------------
# ПОИСК И РАЗБОР ПУБЛИЧНЫХ СТРАНИЦ THREADS
# --------------------------------------------------

def search_url(term, mode):
    params = urllib.parse.urlencode({
        "q": term,
        "serp_type": mode,
    })

    return f"https://www.threads.com/search?{params}"


def walk_json(value):
    """Рекурсивно ищет объекты публикаций внутри JSON."""

    if isinstance(value, dict):
        code = value.get("code")
        caption = value.get("caption")

        if isinstance(caption, dict):
            caption_text = caption.get("text", "")
        elif isinstance(caption, str):
            caption_text = caption
        else:
            caption_text = ""

        user = value.get("user") or {}

        if not isinstance(user, dict):
            user = {}

        username = (
            user.get("username")
            or value.get("username")
            or "unknown"
        )

        if (
            isinstance(code, str)
            and caption_text
            and (
                "taken_at" in value
                or "like_count" in value
                or "pk" in value
            )
        ):
            yield {
                "id": code,
                "username": username,
                "text": html.unescape(str(caption_text)).strip(),
                "permalink": (
                    f"https://www.threads.com/"
                    f"@{username}/post/{code}"
                ),
                "timestamp": value.get("taken_at", 0),
            }

        for child in value.values():
            yield from walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_json_blocks(page):
    """
    Извлекает JSON из блоков application/json.
    Структура страниц Threads может меняться.
    """

    pattern = re.compile(
        r'<script[^>]*type=["\']application/json["\'][^>]*>'
        r"(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(page):
        raw = html.unescape(match.group(1).strip())

        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def fetch_public_posts(term, mode):
    url = search_url(term, mode)
    print(f"Поиск: {term} [{mode}]")

    page = get_page(url)
    posts = {}

    for block in extract_json_blocks(page):
        for post in walk_json(block):
            posts[post["id"]] = post

    print(f"Найдено объектов: {len(posts)}")
    return list(posts.values())


# --------------------------------------------------
# ФИЛЬТРАЦИЯ
# --------------------------------------------------

def is_relevant(post):
    text = post.get("text", "").strip()

    if not text:
        return False

    if not TOPIC_RE.search(text):
        return False

    if not INTENT_RE.search(text):
        return False

    return True


# --------------------------------------------------
# СОХРАНЕНИЕ УЖЕ НАЙДЕННЫХ ПОСТОВ
# --------------------------------------------------

def load_state():
    if not SEEN_FILE.exists():
        return None

    try:
        with SEEN_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

        if isinstance(state, dict) and isinstance(state.get("ids"), list):
            return state

    except (OSError, json.JSONDecodeError):
        pass

    return None


def save_state(ids, initialized=True):
    state = {
        "initialized": initialized,
        "ids": list(ids)[-MAX_SEEN:],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    temporary_file = SEEN_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False)

    temporary_file.replace(SEEN_FILE)


# --------------------------------------------------
# ОСНОВНОЙ ЦИКЛ
# --------------------------------------------------

def run_once():
    state = load_state()

    # Если база отсутствует, заполняем её без уведомлений.
    first_run = state is None or not state.get("initialized", False)

    seen = set(state.get("ids", [])) if state else set()
    found = {}

    for term in SEARCH_TERMS:
        for mode in SEARCH_MODES:
            try:
                posts = fetch_public_posts(term, mode)

                for post in posts:
                    found[post["id"]] = post

            except Exception as error:
                print(
                    f"Не удалось выполнить поиск "
                    f"«{term}» [{mode}]: {error}",
                    file=sys.stderr,
                )

            # Небольшая пауза между запросами.
            time.sleep(2)

    if not found:
        print(
            "Публикации не извлечены. Возможно, Threads "
            "изменил страницу или ограничил запросы."
        )
        # Не меняем сохранённую базу при неудачном поиске.
        return

    if first_run:
        save_state(set(seen) | set(found.keys()))
        print(
            f"Первый запуск: сохранено {len(found)} публикаций. "
            "Уведомления пока не отправляются."
        )
        return

    new_ids = set(found.keys()) - seen
    new_posts = [
        post for post_id, post in found.items()
        if post_id in new_ids and is_relevant(post)
    ]

    sent_ids = set()

    for post in new_posts:
        message = (
            "🧥 Новая публикация о секонд-хенде / винтаже\n\n"
            f"Автор: @{post['username']}\n\n"
            f"{post['text']}\n\n"
            f"{post['permalink']}"
        )

        if telegram_send(message):
            sent_ids.add(post["id"])

        time.sleep(1)

    # Сохраняем все увиденные ID, включая нерелевантные,
    # чтобы повторно не обрабатывать одни и те же публикации.
    save_state(seen | set(found.keys()))

    print(
        f"Цикл завершён. Новых найденных публикаций: "
        f"{len(new_ids)}; подходящих: {len(new_posts)}; "
        f"отправлено: {len(sent_ids)}."
    )


def main():
    print("Монитор публичных публикаций Threads запущен.")
    print("Тематика: секонд-хенд и винтажная одежда в России.")

    if "--once" in sys.argv:
        run_once()
        return

    while True:
        try:
            run_once()
        except Exception as error:
            print(f"Ошибка цикла: {error}", file=sys.stderr)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
        return run_once()
    while True:
        run_once()
        time.sleep(POLL)


if __name__ == "__main__":
    main()

