import os
import re
import json
import time
import hashlib
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("lead-radar")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()  # optional
STATE_FILE = Path("leads_state.json")
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "10"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "55"))
USER_AGENT = "LeadRadar/1.0 (RSS lead monitoring; respectful low-volume access)"
TIMEOUT = 20

# Queries focus on explicit buying intent rather than general conversation.
SEARCHES = [
    ("MMA / Fitness Coaching", '"looking for" (MMA coach OR boxing coach OR kickboxing coach OR online personal trainer)'),
    ("MMA / Fitness Coaching", '"recommend" (boxing coach OR MMA coach OR online fitness coach)'),
    ("English Lessons", '"looking for" (English tutor OR English teacher OR conversation practice)'),
    ("English Lessons", '"recommend" "English tutor" online'),
    ("Russian Lessons", '"looking for" (Russian tutor OR Russian teacher OR learn Russian online)'),
    ("Websites", '"looking for" (web designer OR website developer OR landing page)'),
    ("Telegram Bots / Automation", '"looking for" (Telegram bot developer OR automation developer OR chatbot developer)'),
    ("AI / Marketing", '"looking for" (AI automation OR social media manager OR content creator)'),
    ("Translation", '"looking for" (Arabic translator OR Russian translator OR Ukrainian translator OR English translator)'),
]

INTENT_PHRASES = [
    "looking for", "need a", "need an", "any recommendations", "can anyone recommend",
    "recommend someone", "recommend a", "hire", "hiring", "seeking", "who can",
    "where can i find", "want to hire", "looking to hire", "need help with",
    "Ð¸ÑÑ", "Ð½ÑÐ¶ÐµÐ½", "Ð½ÑÐ¶Ð½Ð°", "Ð½ÑÐ¶Ð½Ñ", "Ð¿Ð¾ÑÐ¾Ð²ÐµÑÑÐ¹ÑÐµ", "ÐºÑÐ¾ Ð¼Ð¾Ð¶ÐµÑ", "Ð¸ÑÐµÐ¼ ÑÐ¿ÐµÑÐ¸Ð°Ð»Ð¸ÑÑÐ°",
    "busco", "necesito", "recomiendan", "cherche", "besoin de", "suche", "brauche",
]
LOW_INTENT_PHRASES = [
    "my business offers", "we offer", "i offer", "my services", "course announcement",
    "job vacancy", "we are hiring", "vacancy", "giveaway", "free course",
]
CATEGORY_TERMS = {
    "MMA / Fitness Coaching": ["mma", "boxing", "kickboxing", "muay thai", "fitness coach", "personal trainer", "self defense", "combat fitness"],
    "English Lessons": ["english tutor", "english teacher", "learn english", "english lessons", "conversation practice"],
    "Russian Lessons": ["russian tutor", "russian teacher", "learn russian", "russian lessons"],
    "Websites": ["web designer", "website", "web developer", "landing page", "wordpress", "shopify"],
    "Telegram Bots / Automation": ["telegram bot", "chatbot", "automation", "workflow", "bot developer"],
    "AI / Marketing": ["ai automation", "social media manager", "content creator", "marketing automation", "smm"],
    "Translation": ["translator", "translation", "arabic", "ukrainian", "russian language"],
}
NEGATIVE_TERMS = [
    "free template", "for school project", "homework", "definition of", "what is mma",
    "what is a website", "course syllabus", "job vacancy", "we are hiring", "internship",
]

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": [], "updated_at": None}

def save_state(state):
    # Keep state file bounded to avoid an unbounded repo file.
    state["seen"] = state.get("seen", [])[-5000:]
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()

def stable_id(url, title, summary):
    key = (url or "") + "|" + (title or "") + "|" + (summary or "")
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()[:24]

def score_item(category, title, summary):
    text = (title + " " + summary).lower()
    score = 20
    reasons = []
    intent_hits = [p for p in INTENT_PHRASES if p in text]
    if intent_hits:
        score += min(35, 15 + 5 * (len(intent_hits) - 1))
        reasons.append("explicit request: " + ", ".join(intent_hits[:2]))
    matched = [term for term in CATEGORY_TERMS.get(category, []) if term in text]
    if matched:
        score += min(25, 10 + 5 * (len(matched) - 1))
        reasons.append("service match: " + ", ".join(matched[:3]))
    if any(p in text for p in ["online", "remote", "virtual", "online lessons"]):
        score += 8
        reasons.append("online-friendly")
    negatives = [p for p in LOW_INTENT_PHRASES + NEGATIVE_TERMS if p in text]
    if negatives:
        score -= min(35, 15 + 5 * (len(negatives) - 1))
        reasons.append("possible low intent: " + ", ".join(negatives[:2]))
    if not intent_hits:
        score -= 10
    return max(0, min(100, score)), reasons

def google_news_rss(query):
    encoded = urllib.parse.quote(query)
    return "https://news.google.com/rss/search?q=" + encoded + "&hl=en-US&gl=US&ceid=US:en"

def reddit_rss(query):
    encoded = urllib.parse.quote(query)
    return "https://www.reddit.com/search.rss?q=" + encoded + "&sort=new"

def fetch_rss(url, source, category):
    items = []
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        for entry in parsed.entries[:20]:
            title = clean(getattr(entry, "title", ""))
            summary = clean(getattr(entry, "summary", "") or getattr(entry, "description", ""))
            link = getattr(entry, "link", "") or ""
            if not title or not link:
                continue
            published = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
            items.append({
                "source": source, "category": category, "title": title,
                "summary": summary[:1500], "url": link, "published": published,
            })
        LOG.info("%s: %d items", source, len(items))
    except Exception as exc:
        LOG.warning("Source unavailable (%s): %s", source, exc)
    return items

def fetch_youtube(query, category):
    if not YOUTUBE_API_KEY:
        return []
    url = "https://www.googleapis.com/youtube/v3/search"
    try:
        response = requests.get(url, params={
            "part": "snippet", "q": query, "type": "video", "order": "date",
            "maxResults": 10, "key": YOUTUBE_API_KEY,
        }, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            results.append({
                "source": "YouTube", "category": category,
                "title": clean(snippet.get("title", "")),
                "summary": clean(snippet.get("description", ""))[:1500],
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "published": snippet.get("publishedAt", ""),
            })
        return results
    except Exception as exc:
        LOG.warning("YouTube API unavailable: %s", exc)
        return []

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID in GitHub Secrets.")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram API returned an unsuccessful response.")

def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise SystemExit("ERROR: configure TELEGRAM_TOKEN and TELEGRAM_CHAT_ID in GitHub Secrets.")
    state = load_state()
    seen = set(state.get("seen", []))
    found = []

    for category, query in SEARCHES:
        # Use two independent RSS entry points. Each source can fail without stopping the run.
        found.extend(fetch_rss(google_news_rss(query), "Google News RSS", category))
        found.extend(fetch_rss(reddit_rss(query), "Reddit RSS", category))
        time.sleep(1.0)

    # Optional YouTube search, only when an API key is configured.
    yt_queries = [
        ("MMA / Fitness Coaching", '"looking for" boxing coach online'),
        ("English Lessons", '"looking for" English tutor online'),
        ("Websites", '"looking for" website developer'),
        ("Telegram Bots / Automation", '"looking for" Telegram bot developer'),
    ]
    for category, query in yt_queries:
        found.extend(fetch_youtube(query, category))
        time.sleep(0.25)

    scored = []
    for item in found:
        item_id = stable_id(item["url"], item["title"], item["summary"])
        if item_id in seen:
            continue
        score, reasons = score_item(item["category"], item["title"], item["summary"])
        if score < MIN_SCORE:
            continue
        item["id"] = item_id
        item["score"] = score
        item["reasons"] = reasons
        scored.append(item)

    # Prefer strongest leads; send a bounded number per run.
    scored.sort(key=lambda x: x["score"], reverse=True)
    alerts = scored[:MAX_ALERTS_PER_RUN]
    for item in alerts:
        published = item["published"] or "date not provided"
        message = (
            f"ð¯ LEAD RADAR â {item['score']}/100\n"
            f"Category: {item['category']}\n"
            f"Source: {item['source']}\n\n"
            f"{item['title']}\n\n"
            f"{item['summary'][:650]}\n\n"
            f"Why selected: {', '.join(item['reasons']) or 'keyword match'}\n"
            f"Published: {published}\n"
            f"{item['url']}"
        )
        try:
            send_telegram(message[:3900])
            seen.add(item["id"])
            LOG.info("Sent lead score=%s category=%s", item["score"], item["category"])
            time.sleep(0.5)
        except Exception as exc:
            LOG.error("Telegram send failed: %s", exc)

    # Mark low-score items seen too, so they are not reconsidered every run.
    # Keep a stable set and cap it to a recent window.
    for item in found:
        seen.add(stable_id(item["url"], item["title"], item["summary"]))
    state["seen"] = list(seen)[-5000:]
    save_state(state)
    LOG.info("Finished. fetched=%d qualified=%d sent=%d", len(found), len(scored), len(alerts))

if __name__ == "__main__":
    main()
