
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
LIMIT = 6

SEARCHES = [
    "South Africa tourism travel safety",
    "Cape Town tourism visitor safety",
    "South Africa SANParks travel tourism",
    "South Africa tourism airlines",
    "South Africa tourism department SATSA travel",
    "South Korea tourism travel",
    "Seoul Jeju tourism travel news",
    "Korea tourism travel safety flights",
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

    # Mixed English headlines with a Korean publisher suffix still need translation.
    letters = re.findall(r"[A-Za-z]", text)
    korean = re.findall(r"[가-힣]", text)
    if korean and len(korean) >= len(letters):
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
            timeout=25,
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






def title_based_summary(title_ko):
    # State only what the headline supports; never imply article-body access.
    title = re.sub(r'\\s+[-–]\\s+[^-–]{2,65}
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
    if len(raw) < 12:
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
                # Headline-only RSS does not support a factual article summary.
                description = title
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
            item['region'] = infer_region(item)
            if not relevant_story(item):
                continue
            items.append(item)
    return sorted(items, key=lambda x: (x['score'], x['published_at']), reverse=True)


def infer_region(item):
    """Classify by the article itself, never by the search query."""
    title = str(item.get('title') or item.get('title_ko') or '').lower()
    description = str(item.get('description') or '').lower()
    content = title + ' ' + description
    za_terms = ('south africa', 'south african', 'cape town', 'johannesburg',
                'pretoria', 'durban', 'western cape', 'eastern cape',
                'kruger', 'satsa', 'sanparks', '남아공', '남아프리카',
                '케이프타운', '요하네스버그')
    kr_terms = ('south korea', 'south korean', 'republic of korea',
                'korean tourism', 'korea tourism',
                'seoul', 'jeju', 'busan', '한국', '대한민국',
                '서울', '제주', '부산', '방한')
    # Regional stories must be about the destination, not merely name an airline.
    if any(term in title for term in za_terms):
        return 'ZA'
    if any(term in title for term in kr_terms):
        return 'KR'
    return 'INT'


def relevant_story(item):
    text = (str(item.get('title') or item.get('title_ko') or '') + ' ' +
            str(item.get('description') or '')).lower()
    # Avoid sports event advisories and incidental travel references.
    if any(x in text for x in ('steelers', 'saints game', 'nfl game',
                                'football match', 'nba game')):
        return False
    return any(x in text for x in ('touris', 'travel', 'flight', 'airline',
                                    'airport', 'visa', 'visitor', 'hotel',
                                    'national park', '여행', '관광', '항공', '비자'))


def load_previous():
    if not OUTPUT.exists():
        return []
    try:
        data = json.loads(OUTPUT.read_text(encoding='utf-8'))
        return [dict(x, region=infer_region(x)) for x in data.get('top5', []) if is_recent(x.get('published_at')) and relevant_story(x) and re.search(r'[가-힣]', x.get('title_ko', ''))]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def main():
    candidates = fetch_candidates()
    print('Candidates with descriptions:', len(candidates))
    previous = load_previous()
    results = []
    used = set()
    quotas = {"ZA": 3, "KR": 3}
    # Translate candidates inside each regional pool, not after selecting only
    # a few. A translation failure must not eliminate an entire region.
    for region, count in quotas.items():
        pool = [x for x in candidates if x.get('region') == region]
        for item in pool:
            if sum(x['region'] == region for x in results) >= count:
                break
            if item['source_url'] in used:
                continue
            title_ko = korean_title(item['title'])
            if not title_ko:
                continue
            summary_ko = (translate_ko(item['description'])
                          if item['description'] != item['title'] else '')
            if not summary_ko or summary_ko.strip() == title_ko.strip():
                summary_ko = title_based_summary(title_ko)
            results.append({
                'title_ko': title_ko,
                'summary_ko': summary_ko,
                'source': item['source'],
                'source_url': item['source_url'],
                'published_at': item['published_at'],
                'region': region,
            })
            used.add(item['source_url'])
        # Previously published stories can fill only their own region.
        for item in previous:
            if sum(x['region'] == region for x in results) >= count:
                break
            link = item.get('source_url', '')
            if (item.get('region') == region and link not in used
                    and item.get('title_ko') and item.get('summary_ko')):
                results.append(dict(item, region=region))
                used.add(link)
    # Preferred 2:2:1 mix, but always fill five slots from any region.
    # This is a fallback, not a replacement for regional sourcing.
    for item in candidates:
        if len(results) >= LIMIT:
            break
        link = item['source_url']
        if link in used or item.get('region') not in quotas:
            continue
        title_ko = korean_title(item['title'])
        if not title_ko:
            continue
        summary_ko = (translate_ko(item['description'])
                      if item['description'] != item['title'] else '')
        if not summary_ko or summary_ko.strip() == title_ko.strip():
            summary_ko = title_based_summary(title_ko)
        results.append({
            'title_ko': title_ko, 'summary_ko': summary_ko,
            'source': item['source'], 'source_url': link,
            'published_at': item['published_at'], 'region': item['region'],
        })
        used.add(link)
    for item in previous:
        if len(results) >= LIMIT:
            break
        link = item.get('source_url', '')
        if link not in used and item.get('title_ko') and infer_region(item) in quotas:
            results.append(dict(item, region=infer_region(item)))
            used.add(link)
    counts = {region: sum(x['region'] == region for x in results)
              for region in quotas}
    print('TOP 5 regional distribution:', counts)
    results = [x for x in results if x['region'] in quotas]
    results.sort(key=lambda x: x['published_at'], reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        'updated_at': datetime.now(timezone.utc).timestamp(),
        'top5': results[:LIMIT],
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('TOP 5 generated:', len(results[:LIMIT]))


if __name__ == '__main__':
    main()
, '', title_ko).strip()
    return '제목 기준: ' + title.rstrip('.。') + '.'


def korean_title(text):
    translated = translate_ko(text)
    if translated and re.search(r'[가-힣]', translated):
        return translated
    # Do not label English text as a Korean translation.
    return ''


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
    if len(raw) < 12:
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
                # Headline-only RSS does not support a factual article summary.
                description = title
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
            item['region'] = infer_region(item)
            if not relevant_story(item):
                continue
            items.append(item)
    return sorted(items, key=lambda x: (x['score'], x['published_at']), reverse=True)


def infer_region(item):
    """Classify by the article itself, never by the search query."""
    title = str(item.get('title') or item.get('title_ko') or '').lower()
    description = str(item.get('description') or '').lower()
    content = title + ' ' + description
    za_terms = ('south africa', 'south african', 'cape town', 'johannesburg',
                'pretoria', 'durban', 'western cape', 'eastern cape',
                'kruger', 'satsa', 'sanparks', '남아공', '남아프리카',
                '케이프타운', '요하네스버그')
    kr_terms = ('south korea', 'south korean', 'republic of korea',
                'korean tourism', 'korea tourism',
                'seoul', 'jeju', 'busan', '한국', '대한민국',
                '서울', '제주', '부산', '방한')
    # Regional stories must be about the destination, not merely name an airline.
    if any(term in title for term in za_terms):
        return 'ZA'
    if any(term in title for term in kr_terms):
        return 'KR'
    return 'INT'


def relevant_story(item):
    text = (str(item.get('title') or item.get('title_ko') or '') + ' ' +
            str(item.get('description') or '')).lower()
    # Avoid sports event advisories and incidental travel references.
    if any(x in text for x in ('steelers', 'saints game', 'nfl game',
                                'football match', 'nba game')):
        return False
    return any(x in text for x in ('touris', 'travel', 'flight', 'airline',
                                    'airport', 'visa', 'visitor', 'hotel',
                                    'national park', '여행', '관광', '항공', '비자'))


def load_previous():
    if not OUTPUT.exists():
        return []
    try:
        data = json.loads(OUTPUT.read_text(encoding='utf-8'))
        return [dict(x, region=infer_region(x)) for x in data.get('top5', []) if is_recent(x.get('published_at')) and relevant_story(x)]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def main():
    candidates = fetch_candidates()
    print('Candidates with descriptions:', len(candidates))
    previous = load_previous()
    results = []
    used = set()
    quotas = {"ZA": 2, "KR": 2, "INT": 1}
    # Translate candidates inside each regional pool, not after selecting only
    # a few. A translation failure must not eliminate an entire region.
    for region, count in quotas.items():
        pool = [x for x in candidates if x.get('region') == region]
        for item in pool:
            if sum(x['region'] == region for x in results) >= count:
                break
            if item['source_url'] in used:
                continue
            title_ko = translate_ko(item['title'])
            summary_ko = translate_ko(item['description'])
            if not title_ko:
                title_ko = item['title']
            if not summary_ko or summary_ko.strip() == title_ko.strip():
                summary_ko = '자세한 내용은 제목을 클릭해 원문에서 확인하세요.'
            results.append({
                'title_ko': title_ko,
                'summary_ko': summary_ko,
                'source': item['source'],
                'source_url': item['source_url'],
                'published_at': item['published_at'],
                'region': region,
            })
            used.add(item['source_url'])
        # Previously published stories can fill only their own region.
        for item in previous:
            if sum(x['region'] == region for x in results) >= count:
                break
            link = item.get('source_url', '')
            if (item.get('region') == region and link not in used
                    and item.get('title_ko') and item.get('summary_ko')):
                results.append(dict(item, region=region))
                used.add(link)
    # Preferred 2:2:1 mix, but always fill five slots from any region.
    # This is a fallback, not a replacement for regional sourcing.
    for item in candidates:
        if len(results) >= LIMIT:
            break
        link = item['source_url']
        if link in used:
            continue
        title_ko = translate_ko(item['title']) or item['title']
        summary_ko = translate_ko(item['description'])
        if not summary_ko or summary_ko.strip() == title_ko.strip():
            summary_ko = '자세한 내용은 제목을 클릭해 원문에서 확인하세요.'
        results.append({
            'title_ko': title_ko, 'summary_ko': summary_ko,
            'source': item['source'], 'source_url': link,
            'published_at': item['published_at'], 'region': item['region'],
        })
        used.add(link)
    for item in previous:
        if len(results) >= LIMIT:
            break
        link = item.get('source_url', '')
        if link not in used and item.get('title_ko'):
            results.append(dict(item, region=infer_region(item)))
            used.add(link)
    counts = {region: sum(x['region'] == region for x in results)
              for region in quotas}
    print('TOP 5 regional distribution:', counts)
    results.sort(key=lambda x: x['published_at'], reverse=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        'updated_at': datetime.now(timezone.utc).timestamp(),
        'top5': results[:LIMIT],
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('TOP 5 generated:', len(results[:LIMIT]))


if __name__ == '__main__':
    main()
