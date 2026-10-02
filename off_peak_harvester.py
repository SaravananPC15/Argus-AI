"""
off_peak_harvester.py — Protocol Off-Peak Data Harvesting.

BUILDS ON, DOESN'T DUPLICATE: scraping_vanguard.py already does polite,
robots.txt-respecting fetching ON DEMAND, when you explicitly ask for
it. What this protocol adds is autonomy -- a scheduler that wakes up
during a configured off-peak window and fetches a configured list of
sources on its own -- plus real headless-browser rendering via
Playwright (already a requirements.txt dependency here, just not
previously wired to anything) for pages that need JavaScript to show
their content, which scraping_vanguard's plain requests+BeautifulSoup
fetch can't do. The robots.txt check itself is IMPORTED from
scraping_vanguard, not reimplemented, so both the on-demand and
autonomous paths respect the exact same rule.

SCOPE, DELIBERATELY: this fetches PUBLIC pages YOU configure (RSS
feeds, public dataset pages, a syllabus/announcements page) -- the same
ethical boundary scraping_vanguard.py already draws. It doesn't attempt
to bypass logins, paywalls, CAPTCHAs, or rate limits, and it ships with
zero pre-configured targets -- you tell it what to watch via
harvest_targets.json (see add_target() / SETUP.md).
"""

import datetime
import hashlib
import json
import os
import time

import scraping_vanguard

ARCHIVE_DIR = "harvest_vault"
DEFAULT_CONFIG_PATH = "harvest_targets.json"
SECONDS_BETWEEN_FETCHES = 2  # same "don't hammer the target" pacing scraping_vanguard already uses


def _within_off_peak_window(now: datetime.datetime, start_hour: int, end_hour: int) -> bool:
    """True if `now` falls in [start_hour, end_hour). Handles a window
    that wraps past midnight (start_hour > end_hour, e.g. 1 AM-6 AM
    would be start=1 end=6 -- NOT wrapping; a wrapping example is
    start=22 end=6, i.e. 10 PM through 6 AM) as well as a same-day
    window."""
    hour = now.hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def load_targets(config_path: str = DEFAULT_CONFIG_PATH) -> list:
    if not os.path.exists(config_path):
        return []
    with open(config_path) as f:
        return json.load(f)


def save_targets(targets: list, config_path: str = DEFAULT_CONFIG_PATH):
    with open(config_path, "w") as f:
        json.dump(targets, f, indent=2)


def add_target(url: str, render_js: bool = False, config_path: str = DEFAULT_CONFIG_PATH):
    targets = load_targets(config_path)
    if any(t["url"] == url for t in targets):
        return targets
    targets.append({"url": url, "render_js": render_js})
    save_targets(targets, config_path)
    return targets


def _archive_path(url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(ARCHIVE_DIR, f"{digest}.json")


def _fetch_with_playwright(url: str, timeout_ms: int = 15000) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            text = page.inner_text("body")
        finally:
            browser.close()
    return text[:20000]  # same size-cap spirit already used elsewhere in this codebase


def fetch_target(url: str, render_js: bool = False) -> dict:
    """Fetches one target. render_js=True uses real headless Chromium
    (Playwright) for pages that need JS to show content; False uses
    scraping_vanguard's existing requests-based fetch (faster, and
    enough for most static pages/RSS). Either way, robots.txt is
    checked FIRST via scraping_vanguard's own check -- same rule, both
    paths."""
    if not scraping_vanguard._robots_allow(url):
        return {"url": url, "ok": False, "error": "disallowed by robots.txt"}
    try:
        text = _fetch_with_playwright(url) if render_js else scraping_vanguard.fetch_public_page_text(url)
        return {"url": url, "ok": True, "text": text,
                "fetched_at": datetime.datetime.now().isoformat()}
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}


def harvest_once(config_path: str = DEFAULT_CONFIG_PATH) -> list:
    """Fetches every configured target once, archiving successes to
    ARCHIVE_DIR. This is what 'harvest now' / an on-demand action
    calls; run_scheduler() below is what waits for the off-peak window
    before calling this on its own."""
    targets = load_targets(config_path)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    results = []
    for i, target in enumerate(targets):
        result = fetch_target(target["url"], render_js=target.get("render_js", False))
        results.append(result)
        if result["ok"]:
            with open(_archive_path(target["url"]), "w") as f:
                json.dump(result, f, indent=2)
        if i < len(targets) - 1:
            time.sleep(SECONDS_BETWEEN_FETCHES)
    return results


def run_scheduler(config_path: str = DEFAULT_CONFIG_PATH, start_hour: int = 1, end_hour: int = 6,
                   check_interval_seconds: int = 1800):
    """Blocking loop: checks every check_interval_seconds whether we're
    in the off-peak window (default 1 AM-6 AM local time) and haven't
    already harvested today; if so, runs harvest_once(). Run in its own
    thread, same as this project's other background services (see
    launch.py)."""
    last_harvest_date = None
    print(f"[Off-Peak Harvester] Watching for the {start_hour:02d}:00-{end_hour:02d}:00 window.")
    while True:
        now = datetime.datetime.now()
        if _within_off_peak_window(now, start_hour, end_hour) and last_harvest_date != now.date():
            targets = load_targets(config_path)
            print(f"[Off-Peak Harvester] In window -- harvesting {len(targets)} target(s)...")
            results = harvest_once(config_path)
            ok_count = sum(1 for r in results if r["ok"])
            print(f"[Off-Peak Harvester] Done: {ok_count}/{len(results)} succeeded.")
            last_harvest_date = now.date()
        time.sleep(check_interval_seconds)


def _self_test():
    import datetime as dt

    # 1. Window logic, same-day and midnight-wrapping.
    cases = [
        (dt.datetime(2026, 7, 23, 3, 0), 1, 6, True),    # 3 AM inside 1-6 AM
        (dt.datetime(2026, 7, 23, 8, 0), 1, 6, False),   # 8 AM outside 1-6 AM
        (dt.datetime(2026, 7, 23, 23, 0), 22, 6, True),  # 11 PM inside wrapping 22-6
        (dt.datetime(2026, 7, 23, 2, 0), 22, 6, True),   # 2 AM inside wrapping 22-6
        (dt.datetime(2026, 7, 23, 12, 0), 22, 6, False), # noon outside wrapping 22-6
    ]
    for now, start, end, expected in cases:
        actual = _within_off_peak_window(now, start, end)
        assert actual == expected, f"{now.hour}:00 in [{start},{end}) -> {actual}, expected {expected}"
    print("[1/3] Off-peak window logic (same-day + midnight-wrapping): OK")

    # 2. load/save/add_target round-trip.
    import tempfile
    tmp_config = os.path.join(tempfile.gettempdir(), "argus_test_harvest_targets.json")
    if os.path.exists(tmp_config):
        os.remove(tmp_config)
    add_target("https://example.com/feed.xml", config_path=tmp_config)
    add_target("https://example.com/dataset", render_js=True, config_path=tmp_config)
    add_target("https://example.com/feed.xml", config_path=tmp_config)  # duplicate, should not double-add
    targets = load_targets(tmp_config)
    assert len(targets) == 2, f"expected 2 targets after de-duped add, got {len(targets)}"
    assert targets[1]["render_js"] is True
    os.remove(tmp_config)
    print("[2/3] Target config load/save/de-duplication: OK")

    # 3. robots.txt gate blocks a fetch BEFORE any network/browser call happens
    #    (mocks scraping_vanguard's real check so this doesn't need network).
    import unittest.mock as mock
    with mock.patch.object(scraping_vanguard, "_robots_allow", return_value=False):
        result = fetch_target("https://example.com/private")
        assert result == {"url": "https://example.com/private", "ok": False,
                           "error": "disallowed by robots.txt"}
    print("[3/3] robots.txt disallow short-circuits before any fetch attempt: OK")

    print("\nAll off_peak_harvester self-tests passed.")


if __name__ == "__main__":
    _self_test()
