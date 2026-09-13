import os
import json
import datetime
import feedparser
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# 1. StariaPj 채널 우대 키워드 (가산점 부여)
STARIA_KEYWORDS = [
    "관광", "가이드", "투어", "힐링", "별보기", "Stargazing", "미식", "식문화", 
    "Culinary", "아프리카", "아시아", "남아공", "Western Cape", "Northern Cape", 
    "케이프타운", "국립공원", "자연", "전통", "K-culture", "스토리"
]

# 2. 지역 감지 키워드
REGION_PATTERNS = {
    "KR": ["한국", "대한민국", "서울", "K-", "Korea", "Korean"],
    "SA": ["남아공", "남아프리카", "Western Cape", "Northern Cape", "Cape Town", "South Africa"],
    "ASIA": ["아시아", "일본", "중국", "베트남", "태국", "인도네시아", "Asia"],
    "AFRICA": ["아프리카", "탄자니아", "케냐", "모로코", "이집트", "Africa"]
}

# 3. 데이터 수집 RSS 피드 목록
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=관광+여행+문화&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=South+Africa+tourism+culture&hl=en-ZA&gl=ZA&ceid=ZA:en",
    "https://news.google.com/rss/search?q=Asia+gastronomy+travel&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Africa+gastronomy+tourism&hl=en&gl=US&ceid=US:en"
]

def analyze_entry(title, summary):
    text = f"{title} {summary}"
    detected_regions = set()
    for reg, keywords in REGION_PATTERNS.items():
        if any(kw.lower() in text.lower() for kw in keywords):
            detected_regions.add(reg)
            
    region_count = len(detected_regions)
    if region_count >= 4:
        priority = 1
    elif region_count == 3:
        priority = 2
    elif region_count == 2:
        priority = 3
    else:
        priority = 4

    staria_score = sum(1 for kw in STARIA_KEYWORDS if kw.lower() in text.lower())
    
    return {
        "title": title,
        "summary": summary[:150] + "..." if len(summary) > 150 else summary,
        "priority": priority,
        "regions": list(detected_regions),
        "staria_score": staria_score
    }

def fetch_news():
    items = []
    seen_titles = set()

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            title = entry.get("title", "")
            if title in seen_titles:
                continue
            seen_titles.add(title)
            
            summary = entry.get("summary", "")
            analyzed = analyze_entry(title, summary)
            items.append(analyzed)

    items.sort(key=lambda x: (x["priority"], -x["staria_score"]))
    
    # 우선순위별 수량 제한: 1순위(5개), 2순위(4개), 3순위(3개), 4순위(2개)
    priority_limits = {1: 5, 2: 4, 3: 3, 4: 2}
    prioritized_result = {1: [], 2: [], 3: [], 4: []}
    
    for item in items:
        p = item["priority"]
        if len(prioritized_result[p]) < priority_limits[p]:
            prioritized_result[p].append(item)

    return prioritized_result

def generate_markdown(news_dict):
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    md = f"# 🎬 StariaPj 일일 핫이슈 & 숏츠 기획 리포트 ({today_str})\n\n"
    md += "> **채널 테마**: 관광/가이딩, 별보기, 미식 식문화, 힐링 대자연, 아프리카/아시아 스토리\n\n"
    
    priority_labels = {
        1: "🔥 우선순위 1: 4개 지역(아프리카/아시아/남아공/한국) 공통 핫이슈 (최대 5개)",
        2: "🌟 우선순위 2: 3개 지역 연관 핫이슈 (최대 4개)",
        3: "📌 우선순위 3: 2개 지역 연관 핫이슈 (최대 3개)",
        4: "💡 우선순위 4: 1개 지역 특화 핫이슈 (최대 2개)"
    }

    for p in range(1, 5):
        md += f"## {priority_labels[p]}\n\n"
        items = news_dict[p]
        if not items:
            md += "해당되는 뉴스 항목이 없습니다.\n\n"
            continue
            
        for idx, item in enumerate(items, 1):
            regions_str = ", ".join(item["regions"]) if item["regions"] else "지역특화"
            md += f"### {idx}. {item['title']}\n"
            md += f"- **관련 지역**: `{regions_str}` | **StariaPj 적합도 점수**: {item['staria_score']}점\n"
            md += f"- **핵심 요약**: {item['summary']}\n"
            md += f"- **🎥 Shorts 기획 팁**: 현지 가이드 포인트(남아공/한국)와 연결하여 시각적 현장감 강조 연출 추천\n\n"
            
    return md, today_str

def upload_to_gdrive(content, today_str):
    sa_json = os.environ.get("GDRIVE_SA_KEY")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    if not sa_json or not folder_id:
        print("Google Drive Credentials or Folder ID missing!")
        return

    scopes = [
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/documents"
    ]
    
    creds_dict = json.loads(sa_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    drive_service = build("drive", "v3", credentials=creds)
    docs_service = build("docs", "v1", credentials=creds)

    filename = f"StariaPj_Daily_Report_{today_str}"
    
    # 1. 용량 0 Byte를 소비하는 빈 구글 문서 생성
    file_metadata = {
        "name": filename,
        "parents": [folder_id],
        "mimeType": "application/vnd.google-apps.document"
    }
    
    file = drive_service.files().create(body=file_metadata, fields="id").execute()
    doc_id = file.get("id")
    print(f"Created Google Doc successfully! File ID: {doc_id}")

    # 2. Google Docs API로 텍스트 데이터 작성 (용량 제한 검사 우회)
    requests = [
        {
            "insertText": {
                "location": {"index": 1},
                "text": content
            }
        }
    ]
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
    print("Report content updated successfully!")

if __name__ == "__main__":
    news_data = fetch_news()
    md_content, today_str = generate_markdown(news_data)
    upload_to_gdrive(md_content, today_str)
