#!/usr/bin/env python3
"""Бот: ищет в Threads посты, где есть ДАНАНГ + просьба найти вещь
(кожаная куртка, джинсы, винтажная юбка и т.п.), и шлёт их в Telegram.
Без токенов работает в MOCK-режиме (фейковые посты, вывод в консоль).
"""
import json, os, re, sys, time, urllib.parse, urllib.request

SEEN_FILE = os.environ.get("SEEN_FILE", "seen.json")
THREADS_TOKEN = os.environ.get("THREADS_TOKEN")
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
POLL = int(os.environ.get("POLL_SECONDS", "900"))
REQUIRE_INTENT = os.environ.get("REQUIRE_INTENT", "1") == "1"

DEFAULT_ITEMS = ("кожаная куртка;leather jacket;джинсы;джинсовые штаны;jeans;"
                 "винтажная юбка;vintage skirt;винтаж;vintage")
ITEMS = [i.strip().lower() for i in (os.environ.get("ITEMS") or DEFAULT_ITEMS).split(";") if i.strip()]

CITY_RE = re.compile(r"дананг\w*|da[\s-]?nang|đà[\s-]?nẵng|da[\s-]?nẵng", re.I)

INTENT_RE = re.compile(
    r"ищу|ищем|ищется|подскаж|посоветуй|подкин|где\s+(можно\s+)?(купить|найти|взять)|"
    r"кто\s+(знает|может)|не\s+знаете|нужн|хочу\s+купить|"
    r"looking\s+for|\biso\b|where\s+(to|can|do)\s|anyone\s+know|any\s+recommend|"
    r"recommend|need\s+to\s+find|tìm|cần\s+mua|\?", re.I)

SEARCH_CITIES = ["Дананг", "Danang"]


def stem(w):
    return w[:-2] if len(w) > 5 else w[:-1] if len(w) > 4 else w


def item_matches(text):
    t = text.lower()
    for item in ITEMS:
        if all(stem(w) in t for w in item.split()):
            return item
    return None


def analyze(text):
    if not CITY_RE.search(text):
        return None
    item = item_matches(text)
    if not item:
        return None
    if REQUIRE_INTENT and not INTENT_RE.search(text):
        return None
    return item


def http_json(url, data=None):
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.load(r)


MOCK_POSTS = [
    {"id": "m1", "username": "anna", "text": "Ищу кожаную куртку в Дананге, подскажите где купить?",
     "permalink": "https://www.threads.net/@anna/post/m1"},
    {"id": "m2", "username": "ivan", "text": "Где в Дананге можно найти винтажную юбку? Посоветуйте магазины",
     "permalink": "https://www.threads.net/@ivan/post/m2"},
    {"id": "m3", "username": "olga", "text": "Looking for vintage jeans near Da Nang, any shops?",
     "permalink": "https://www.threads.net/@olga/post/m3"},
    {"id": "m4", "username": "pavel", "text": "Погода в Дананге отличная, идём на пляж",
     "permalink": "https://www.threads.net/@pavel/post/m4"},
    {"id": "m5", "username": "kate", "text": "Ищу кожаную куртку в Москве",
     "permalink": "https://www.threads.net/@kate/post/m5"},
    {"id": "m6", "username": "sam", "text": "Купил джинсы в Дананге, супер",
     "permalink": "https://www.threads.net/@sam/post/m6"},
]


def fetch_threads(query):
    qs = urllib.parse.urlencode({
        "q": query, "search_type": "RECENT",
        "fields": "id,text,permalink,username,timestamp",
        "access_token": THREADS_TOKEN})
    return http_json(f"https://graph.threads.net/keyword_search?{qs}").get("data", [])


def queries():
    return [f"{c} {i}" for c in SEARCH_CITIES for i in ITEMS]


def fetch(query):
    return fetch_threads(query) if THREADS_TOKEN else MOCK_POSTS


def notify(post, item):
    text = (f"🔔 Дананг: ищут «{item}»\n"
            f"@{post.get('username', '?')}: {post.get('text', '')}\n"
            f"{post.get('permalink', '')}")
    if TG_TOKEN and TG_CHAT:
        body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
        http_json(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", body)
    else:
        print("[MOCK TELEGRAM]\n" + text + "\n")


def load_seen():
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def run_once():
    seen, new = load_seen(), 0
    for q in queries():
        try:
            posts = fetch(q)
        except Exception as e:
            print(f"Ошибка запроса «{q}»: {e}", file=sys.stderr)
            continue
        for p in posts:
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            item = analyze(p.get("text", ""))
            if item:
                notify(p, item)
                new += 1
        if not THREADS_TOKEN:
            break
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f)
    print(f"Готово: подходящих постов {new}")


def main():
    mode = "REAL Threads" if THREADS_TOKEN else "MOCK Threads"
    out = "REAL Telegram" if (TG_TOKEN and TG_CHAT) else "MOCK Telegram (консоль)"
    print(f"Старт: {mode} -> {out}; запросов за цикл: {len(queries())}")
    if "--once" in sys.argv:
        return run_once()
    while True:
        run_once()
        time.sleep(POLL)


if __name__ == "__main__":
    main()

