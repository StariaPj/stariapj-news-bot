"""Public tourism headlines only. No email, Drive IDs or credentials."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("flights", "exchanges", "festivals", "mice", "promotions")
WINDOW = 72 * 3600
PATH = Path("public/news.json")

def export_news(report=None, now=None):
    now = now or datetime.now(timezone.utc).timestamp()
    try:
        previous = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        previous = {}
    items = {x["id"]: x for x in previous.get("items", [])
             if x.get("received_at", 0) > now-WINDOW and x.get("received_at", 0) <= now}
    if report:
        for category in CATEGORIES:
            for entry in report.get(category, []):
                link = entry.get("link", "")
                title = entry.get("title", "")
                published = entry.get("pub_ts", 0)
                if not title or not link.startswith(("https://", "http://")):
                    continue
                if not isinstance(published, (int, float)) or not now-WINDOW < published <= now:
                    continue
                key = hashlib.sha256((category+"|"+link+"|"+title).encode()).hexdigest()[:24]
                if key not in items:
                    items[key] = {"id":key, "category":category, "title":title,
                                  "title_ko":entry.get("display_title", title),
                                  "url":link, "published_at":published, "received_at":now}
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps({"updated_at":now, "retention_hours":72,
        "items":sorted(items.values(),key=lambda x:x["received_at"],reverse=True)},
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__":
    export_news()
