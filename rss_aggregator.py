"""
rss_aggregator.py — Protocol RSS Aggregator (Tech Trend Radar).

Polls a small list of RSS/Atom feeds in the background and, when new
entries show up since the last check, summarizes them into a short note
via the local LLM and pushes it through notifier.py — so it shows up
alongside overwatch/aegis/security_warden alerts in the dashboard and
on connected devices, without needing internet-search tool calls.
"""

import time
import json
import os
import feedparser
import ollama
import model_router
import notifier

DEFAULT_FEEDS = [
    "https://hnrss.org/frontpage",
    "https://www.reddit.com/r/MachineLearning/.rss",
]

SEEN_FILE = "audio_cache/rss_seen_ids.json"
POLL_INTERVAL_SECONDS = 60 * 30  # 30 minutes


def _load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    try:
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def _save_seen(seen_ids):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    # Keep this bounded so it doesn't grow forever
    trimmed = list(seen_ids)[-500:]
    with open(SEEN_FILE, "w") as f:
        json.dump(trimmed, f)


def _summarize_entries(entries: list) -> str:
    titles = "\n".join(f"- {e['title']} ({e.get('source', '')})" for e in entries[:8])
    prompt = f"""
    New tech/AI feed items came in. Write ONE short, punchy conversational
    sentence flagging the most notable one(s) — not a list, just a quick
    heads-up like you'd text a friend. No markdown.

    NEW ITEMS:
    {titles}
    """
    try:
        response = ollama.chat(model=model_router.select_model("rss_aggregator"), messages=[
            {'role': 'system', 'content': prompt}
        ])
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[RSS Aggregator Error]: {e}")
        return f"{len(entries)} new items in your tracked feeds."


def check_feeds_once(feed_urls=None):
    """Runs a single check pass. Returns the summary note if new items
    were found, else None. Also queues a notification."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("rss_aggregator"):
            return None
    except Exception:
        pass

    feed_urls = feed_urls or DEFAULT_FEEDS
    seen = _load_seen()
    new_entries = []

    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:10]:
                entry_id = entry.get("id") or entry.get("link")
                if entry_id and entry_id not in seen:
                    new_entries.append({"title": entry.get("title", "Untitled"), "source": url})
                    seen.add(entry_id)
        except Exception as e:
            print(f"[RSS Aggregator] Failed to parse {url}: {e}")

    _save_seen(seen)

    if not new_entries:
        return None

    summary = _summarize_entries(new_entries)
    notifier.queue_alert("rss_aggregator", summary, level="info")
    return summary


def run_background_loop(feed_urls=None):
    """Blocking entry point — run this in its own thread/process."""
    print("[RSS Aggregator] Watching feeds in the background...")
    while True:
        try:
            check_feeds_once(feed_urls)
        except Exception as e:
            print(f"[RSS Aggregator] Loop error: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_background_loop()
