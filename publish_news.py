"""Publish bilingual PDF editions and expire them 48 hours after arrival."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WINDOW=48*3600
PATH=Path("public/news.json")
PDF_DIR=Path("public/pdfs")
SAFE_NAME=re.compile(r"^StariaPj_Daily_Report_\d{4}-\d{2}-\d{2}_\d{4}_KST(?:_en|_ko)?\.pdf$")

def export_news(report=None, pdfs=None, now=None):
    now=now if now is not None else datetime.now(timezone.utc).timestamp()
    try:
        previous=json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError,ValueError):
        previous={}
    editions={}
    for edition in previous.get("newsletters",[]):
        received=edition.get("received_at")
        if isinstance(received,(int,float)) and now-WINDOW < received <= now:
            editions[edition["id"]]=edition
    if report and pdfs:
        issued=datetime.strptime(report["now_kst_str"],"%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Seoul")).timestamp()
        edition_id=report["time_str"]
        received=editions.get(edition_id,{}).get("received_at",now)
        files={}
        PDF_DIR.mkdir(parents=True,exist_ok=True)
        for language in ("en","ko"):
            name=f'StariaPj_Daily_Report_{edition_id}_KST_{language}.pdf'
            if not SAFE_NAME.fullmatch(name): raise ValueError("Invalid PDF filename")
            (PDF_DIR/name).write_bytes(pdfs[language])
            files[language]=name
        editions[edition_id]={"id":edition_id,"title_en":"StariaPj Travel Newsletter",
            "title_ko":"StariaPj 관광 소식지","published_at":issued,"received_at":received,"files":files}
    active={name for edition in editions.values() for name in edition.get("files",{}).values()}
    if PDF_DIR.exists():
        for path in PDF_DIR.glob("*.pdf"):
            if SAFE_NAME.fullmatch(path.name) and path.name not in active:
                path.unlink()
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps({"updated_at":now,"retention_hours":48,
        "newsletters":sorted(editions.values(),key=lambda x:x["received_at"],reverse=True)},
        ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    export_news()
