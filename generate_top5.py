
import calendar
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import feedparser
import requests

OUTPUT = Path("public/top5.json")
DAYS = 5
LIMIT = 5

SEARCHES = [
    "South Africa tourism travel safety",
    "South Africa tourism airlines",
    "South Korea tourism travel",
    "Africa Asia tourism flights",
    "international tourism travel advisory",
]

KEYWORDS = {
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
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 StariaPjTravelNews/1.0"
})

def clean(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
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

        return translated if re.search(r"[가-힣]", translated) else ""

    except (requests.RequestException, ValueError,
            KeyError, IndexError, TypeError):
        return ""






def published_seconds(entry):
    parsed = entry.get('published_parsed') or entry.get('updated_parsed')
    return float(calendar.timegm(parsed)) if parsed else None


def is_recent(timestamp):
    if not isinstance(timestamp, (int, float)):
        return False
    age = datetime.now(timezone.utc).timestamp() - timestamp
    return 0 <= age <= DAYS * 86400


def score(item):
    text = (item['title'] + ' ' + item['description']).lower()
    return sum(points for word, points in KEYWORDS.items() if word in text)


def description_from(entry):
    title = clean(entry.get('title', ''))
    raw = clean(entry.get('summary', '') or entry.get('description', ''))
    # RSS descriptions often contain just a headline, publisher, or list of links.
    # Require at least some additional textual substance, but not the old 90-char minimum.
    if not raw or raw.casefold() == title.casefold():
        return ''
    # Strip title prefix, if repeated.
    if raw.casefold().startswith(title.casefold()):
        raw = raw[len(title):].lstrip(' -:|')
    if len(raw) < 35:
        return ''
    return raw[:750]


def fetch_candidates():
    items = []
    seen = set()
    for search in SEARCHES:
        url = ('https://news.google.com/rss/search?q='
               + quote(search + ' when:5d') + '&hl=en&gl=US&ceid=US:en')
        try:
            response = SESSION.get(url, timeout=25)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            print('RSS fetch failed:', search, exc)
            continue
        print('RSS:', search, 'entries:', len(feed.entries))
        for entry in feed.entries:
            title = clean(entry.get('title', ''))
            link = entry.get('link', '')
            stamp = published_seconds(entry)
            if not title or not link or not is_recent(stamp):
                continue
            description = description_from(entry)
            if not description:
                continue
            key = re.sub(r'\W+', '', title.casefold())[:110]
            if key in seen:
                continue
            seen.add(key)
            source = clean(entry.get('source', {}).get('title', ''))
            if not source:
                source = urlparse(link).netloc or 'Google News'
            item = {'title': title, 'description': description,
                    'source': source, 'source_url': link, 'published_at': stamp}
            item['score'] = score(item)
            items.append(item)
    return sorted(items, key=lambda x: (x['score'], x['published_at']), reverse=True)


def load_previous():
    if not OUTPUT.exists():
        return []
    try:
        data = json.loads(OUTPUT.read_text(encoding='utf-8'))
        return [x for x in data.get('top5', []) if is_recent(x.get('published_at'))]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def main():
    candidates = fetch_candidates()
    print('Candidates with descriptions:', len(candidates))
    previous = load_previous()
    results = []
    used = set()
    for item in candidates:
        if len(results) >= LIMIT:
            break
        title_ko = translate_ko(item['title'])
        summary_ko = translate_ko(item['description'])
        # Avoid inventing 2-3 sentences when the feed provides only one.
        if not title_ko or not summary_ko or len(summary_ko) < 20:
            continue
        results.append({
            'title_ko': title_ko,
            'summary_ko': summary_ko,
            'source': item['source'],
            'source_url': item['source_url'],
            'published_at': item['published_at'],
        })
        used.add(item['source_url'])
    # Keep recent prior items if RSS or translation temporarily fails.
    for item in previous:
        if len(results) >= LIMIT:
            break
        link = item.get('source_url', '')
        if link not in used and item.get('title_ko') and item.get('summary_ko'):
            results.append(item)
            used.add(link)
    results.sort(key=lambda x: x['published_at'], reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        'updated_at': datetime.now(timezone.utc).timestamp(),
        'top5': results[:LIMIT],
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('TOP 5 generated:', len(results[:LIMIT]))


if __name__ == '__main__':
    main()
