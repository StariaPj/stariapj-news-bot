"""Publish PDF newsletter references without exposing headlines on the homepage."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WINDOW = 72 * 3600
PATH = Path("public/news.json")
PDF_DIR = Path("public/pdfs")
SAFE_NAME = re.compile(r"^StariaPj_Daily_Report_\d{4}-\d{2}-\d{2}_\d{4}_KST\.pdf$")

def export_news(report=None, pdf_bytes=None, now=None):
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    try:
        previous = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        previous = {}
    editions = {}
    for edition in previous.get("newsletters", []):
        name = edition.get("file", "")
        issued = edition.get("published_at", 0)
        if SAFE_NAME.fullmatch(name) and isinstance(issued, (int, float)):
            if now-WINDOW < issued <= now:
                editions[name] = edition
            else:
                (PDF_DIR/name).unlink(missing_ok=True)
    if report and pdf_bytes:
        issued = datetime.strptime(report["now_kst_str"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Seoul")).timestamp()
        name = f'StariaPj_Daily_Report_{report["time_str"]}_KST.pdf'
        if SAFE_NAME.fullmatch(name) and now-WINDOW < issued <= now:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            (PDF_DIR/name).write_bytes(pdf_bytes)
            editions[name] = {"file": name, "published_at": issued}
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps({"updated_at": now, "retention_hours": 72,
        "newsletters": sorted(editions.values(),key=lambda x:x["published_at"],reverse=True)},
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__ == "__main__":
    export_news()
