
"""Generate Korean TOP 5 tourism headlines for Cafe24.

Output: public/top5.json
Requires: requests, feedparser (already used by news bot).
"""

import json
import re
import html
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
import feedparser

OUTPUT = Path("public/top5.json")
DAYS = 5
MAX_ITEMS = 5

# South Africa, South Korea, international tourism
SEARCHES = [
    "South Africa tourism travel safety",
    "South Africa tourism airlines",
    "South Korea tourism travel",
    "Africa Asia tourism flights",
    "international tourism travel advisory",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 StariaPjTravelNews/1.0"
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def translate_ko(text):
    if not text:
        return ""

    if re.search(r"[가-힣]", text):
        return text

    try:
        response = SESSION.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "ko",
                "dt": "t",
                "q": text[:1800],
            },
            timeout=15,
        )
        response.raise_for_status()

        translated = "".join(
            part[0]
            for part in response.json()[0]
            if part[0]
        ).strip()

        if re.search(r"[가-힣]", translated):
            return translated

    except (requests.RequestException, ValueError,
            KeyError, IndexError, TypeError):
        pass

    return ""


def article_time(entry):
    stamp = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )
    if not stamp:
        return None
    return float(time.mktime(stamp))


def recent(timestamp):
    if timestamp is None:
        return False
    age = datetime.now(timezone.utc).timestamp() - timestamp
    return 0 <= age <= DAYS * 86400


def source_name(entry):
    source = entry.get("source")
    if source:
        name = source.get("title", "")
        if name:
            return clean_text(name)

    link = entry.get("link", "")
    return urlparse(link).netloc or "Google News"


def extract_description(entry):
    raw = entry.get("summary", "")
    text = clean_text(raw)

    title = clean_text(entry.get("title", ""))

    # Google News descriptions sometimes only repeat
    # the headline and publisher; do not invent a summary.
    if not text or text == title:
        return ""

    if len(text) < 90:
        return ""

    # Avoid long or unsupported paraphrases.
    return text[:650].rsplit(" ", 1)[0].strip()


def importance_score(title, description):
    text = (title + " " + description).lower()
    score = 0

    keywords = {
        "travel advisory": 30,
        "travel warning": 30,
        "safety": 25,
        "tourism": 10,
        "airline": 15,
        "flight": 15,
        "visa": 25,
        "airport": 15,
        "south africa": 20,
        "korea": 20,
        "africa": 10,
        "asia": 10,
        "관광": 10,
        "안전": 25,
        "항공": 15,
        "비자": 25,
    }

    for keyword, points in keywords.items():
        if keyword in text:
            score += points

    return score


def fetch_candidates():
    candidates = []
    seen = set()

    for search in SEARCHES:
        rss_url = (
            "https://news.google.com/rss/search?q="
            + quote(search + " when:5d")
            + "&hl=en&gl=US&ceid=US:en"
        )

        try:
            response = SESSION.get(rss_url, timeout=20)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

        except requests.RequestException as exc:
            print("RSS error:", search, exc)
            continue

        for entry in feed.entries:
            title = clean_text(entry.get("title", ""))
            link = entry.get("link", "")
            published = article_time(entry)

            if not title or not link or not recent(published):
                continue

            # Deduplicate repeated headlines.
            key = re.sub(r"\W+", "", title.lower())[:100]
            if key in seen:
                continue
            seen.add(key)

            description = extract_description(entry)

            # Only articles with meaningful description
            # can qualify for an on-page summary.
            if not description:
                continue

            candidates.append({
                "title": title,
                "description": description,
                "link": link,
                "source": source_name(entry),
                "published_at": published,
                "score": importance_score(title, description),
            })

    return sorted(
        candidates,
        key=lambda x: (x["score"], x["published_at"]),
        reverse=True,
    )


def create_summary(description):
    # Translate only supplied source text.
    korean = translate_ko(description)
    if not korean:
        return ""

    sentences = re.split(r"(?<=[.!?。])\s+", korean)
    summary = " ".join(sentences[:3]).strip()

    # Do not display a meaningless short fragment.
    if len(summary) < 45:
        return ""

    return summary[:650]


def main():
    candidates = fetch_candidates()
    results = []

    for item in candidates:
        if len(results) >= MAX_ITEMS:
            break

        title_ko = translate_ko(item["title"])
        summary_ko = create_summary(item["description"])

        if not title_ko or not summary_ko:
            continue

        results.append({
            "title_ko": title_ko,
            "summary_ko": summary_ko,
            "source": item["source"],
            "source_url": item["link"],
            "published_at": item["published_at"],
        })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    # Preserve previous valid results on temporary
    # feed/translation failures, within the 5-day window.
    if not results and OUTPUT.exists():
        try:
            old = json.loads(OUTPUT.read_text(
                encoding="utf-8"
            ))
            results = [
                x for x in old.get("top5", [])
                if recent(x.get("published_at"))
            ][:MAX_ITEMS]
        except (ValueError, OSError, TypeError):
            pass

    payload = {
        "updated_at": datetime.now(
            timezone.utc
        ).timestamp(),
        "top5": results,
    }

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )

    print("TOP 5 generated:", len(results))


if __name__ == "__main__":
    main()
