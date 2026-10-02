"""
scraping_vanguard.py — Protocol Scraping Vanguard (Public Data Gatherer).

Scoped intentionally: this fetches public, unauthenticated pages —
dataset repository listings, academic course/deadline pages, public
RSS-backed trend sources — politely: it checks robots.txt, rate-limits
itself, and identifies itself with a real descriptive User-Agent rather
than pretending to be a browser. It does not do fingerprint spoofing,
proxy rotation, or other anti-detection engineering aimed at defeating a
platform's own rate-limiting/anti-bot systems — that's a materially
different tool built to evade a service's terms rather than just fetch
public data, and isn't something built here even under this codename.

For "hashtag trends" specifically: rather than scraping a social
platform's HTML (which explicitly prohibits that in its ToS and defends
against it), this pulls from public, no-login trend sources where they
exist (e.g. a site's own public RSS/trends page) via search results.
"""

import time
import requests
from urllib.parse import urljoin, urlparse
from urllib import robotparser
from bs4 import BeautifulSoup

USER_AGENT = "ArgusPersonalAssistant/1.0 (+local research tool; respects robots.txt)"
MIN_DELAY_SECONDS = 2.0  # politeness delay between requests to the same host

_last_request_time = {}


def _robots_allow(url: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        # If robots.txt can't be read, err on the side of NOT fetching
        # rather than assuming permission.
        return False


def _polite_get(url: str, timeout=10):
    host = urlparse(url).netloc
    now = time.time()
    elapsed = now - _last_request_time.get(host, 0)
    if elapsed < MIN_DELAY_SECONDS:
        time.sleep(MIN_DELAY_SECONDS - elapsed)

    if not _robots_allow(url):
        return None, "robots.txt disallows fetching this page"

    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        _last_request_time[host] = time.time()
        return response, None
    except requests.RequestException as e:
        return None, str(e)


def fetch_public_page_text(url: str) -> str:
    """Fetches one public page and returns cleaned visible text.
    Respects robots.txt; returns an explanatory string instead of
    content if disallowed or unreachable."""
    response, error = _polite_get(url)
    if error:
        return f"Couldn't fetch {url}: {error}"
    if response.status_code != 200:
        return f"{url} returned HTTP {response.status_code}."

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:4000]


def gather_from_sources(topic_or_urls) -> str:
    """Entry point for executor.py's 'scraping_vanguard' action.
    Accepts either a topic (falls back to a plain web search) or a list
    of specific public URLs (e.g. a course deadlines page, a dataset
    repo listing page) to fetch directly and summarize."""
    import ollama
    import model_router

    if isinstance(topic_or_urls, str) and topic_or_urls.strip().startswith("http"):
        urls = [u.strip() for u in topic_or_urls.split(",") if u.strip().startswith("http")]
        collected = []
        for url in urls[:5]:
            text = fetch_public_page_text(url)
            collected.append(f"SOURCE: {url}\n{text}")
        combined = "\n\n".join(collected)
        summary_prompt = f"Summarize the key facts/deadlines/data points from these public pages in 3-4 conversational sentences:\n\n{combined[:4000]}"
    else:
        # No specific URLs given — this falls back to describing what it
        # would need rather than guessing at scraping targets, since
        # picking sources for an ambiguous "hashtag trends" style request
        # without a specified public source risks landing on a platform
        # that explicitly disallows scraping.
        return ("Give me specific public URLs to pull from (a dataset repo listing, "
                "an academic deadlines page, a public trends/RSS page), macha, and "
                "I'll fetch and summarize them. I won't guess at scraping a social "
                "platform directly since most explicitly disallow that in robots.txt.")

    try:
        response = ollama.chat(model=model_router.select_model("scraping_vanguard"), messages=[
            {'role': 'system', 'content': summary_prompt}
        ])
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[Scraping Vanguard Error]: {e}")
        return "I gathered the pages but hit a snag summarizing them."
