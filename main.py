import io
import os
import sys
import requests
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 1. ReportLab 내장 한글 폰트 등록
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

def fetch_google_news_rss(query):
    """
    Google News RSS를 5초 타임아웃으로 안전하게 파싱 (무장애 수집)
    """
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            return feed.entries[:5]
    except Exception as e:
        print(f"⚠️ RSS 수집 경고 (키워드: {query}): {e}")
    return []

def fetch_youtube_buzz(query, youtube_api_key):
    """
    YouTube Data API를 활용한 영상 조회수/화제성 지수 산출 (선택사항)
    """
    if not youtube_api_key:
        return []
    
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'order': 'viewCount',
        'maxResults': 3,
        'key': youtube_api_key
    }
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get('items', [])
    except Exception as e:
        print(f"⚠️ YouTube API 호출 중 경고: {e}")
    return []

def clean_text(text):
    """ReportLab XML 파싱 오류 방지를 위한 태그 처리"""
    if not text:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def generate_report_data():
    """
    요청된 7개 세부 키워드별 데이터 수집 및 조합
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    # 1) 항공 특가 (남아공발 한국행 & 한국발 남아공행)
    flight_query = '(남아공 OR "South Africa") (한국 OR "Korea" OR 서울) (항공권 OR 항공 OR 특가 OR 프로모션 OR "flight")'
    flight_entries = fetch_google_news_rss(flight_query)
    
    # 2) 아프리카 ↔ 아시아/한국 주제 교류 행사 (한국 내 아프리카 행사 & 남아공 내 아시아 행사)
    exchange_query = '((한국 OR 대한민국) 아프리카 (행사 OR 축제 OR 문화제)) OR ((남아공 OR "South Africa") (아시아 OR "Asia" OR 한국) (행사 OR 축제 OR "festival"))'
    exchange_entries = fetch_google_news_rss(exchange_query)
    
    # 3) 스포츠 빅매치 (아프리카팀 ↔ 아시아/한국팀 경합 이벤트)
    sports_query = '(아프리카 OR 남아공 OR "South Africa") (아시아 OR 한국 OR "Korea") (축구 OR 야구 OR 농구 OR 매치 OR "match" OR "tournament" OR 경기)'
    sports_entries = fetch_google_news_rss(sports_query)
    
    # 4) 미식 축제 (K-Food 미식 축제 & 남아공 South Africa 미식 축제)
    gastro_query = '("K-Food" OR 남아공 OR "South Africa") (미식 OR 푸드 OR "food festival" OR "gastronomy") (축제 OR 페스티벌)'
    gastro_entries = fetch_google_news_rss(gastro_query)
    
    # 5) MICE 행사 (컨벤션, 박람회, 포럼)
    mice_query = '(남아공 OR 대한민국 OR 아프리카) (MICE OR 박람회 OR 컨벤션 OR 포럼 OR "exhibition")'
    mice_entries = fetch_google_news_rss(mice_query)
    
    # 6) 기타 관광 프로모션 및 이벤트 혜택
    promo_query = '(남아공 OR 대한민국 OR 아프리카) (관광 OR 프로모션 OR 이벤트 OR 할인 OR 무료)'
    promo_entries = fetch_google_news_rss(promo_query)
    
    # 7) YouTube 화제성 수집
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    yt_videos = fetch_youtube_buzz("South Africa Korea tourism food festival sports", youtube_api_key)
    
    return {
        'time_str': time_str,
        'now_kst_str': now_kst.strftime('%Y-%m-%d %H:%M:%S'),
        'flights': flight_entries,
        'exchanges': exchange_entries,
        'sports': sports_entries,
        'festivals': gastro_entries,
        'mice': mice_entries,
        'promotions': promo_entries,
        'yt_videos': yt_videos
    }

def create_pdf_bytes(data):
    """
    카테고리별 특보 및 트렌드가 반영된 PDF 생성
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=40
    )
    
    title_style = ParagraphStyle(
        'DocTitle', fontName='HYGothic-Medium', fontSize=18, leading=22,
        textColor=colors.HexColor('#1A365D'), spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        'SubTitle', fontName='HYSMyeongJo-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#4A5568'), spaceAfter=10
    )
    h2_style = ParagraphStyle(
        'Heading2', fontName='HYGothic-Medium', fontSize=11.5, leading=15,
        textColor=colors.HexColor('#2B6CB0'), spaceBefore=8, spaceAfter=4
    )
    body_style = ParagraphStyle(
        'BodyCustom', fontName='HYSMyeongJo-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#2D3748'), spaceAfter=4
    )
    alert_style = ParagraphStyle(
        'AlertCustom', fontName='HYGothic-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#C53030'), spaceAfter=4
    )

    story = []
    
    # 헤더
    story.append(Paragraph("StariaPj 일일 핫이슈 & Tourism/Sports/MICE 특보", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | 양국 교류·미식·스포츠·MICE 통합 트래킹", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#3182CE'), spaceAfter=8))
    
    # 1. ✈️ [항공 특가] 한국 ↔ 남아공 양방향 특가 항공권
    story.append(Paragraph("✈️ [항공 특가] 한국 ↔ 남아공 특가 항공권 & 프로모션", h2_style))
    if data['flights']:
        for item in data['flights']:
            story.append(Paragraph(f"• <b>[특가소식]</b> {clean_text(item.title)}", alert_style))
    else:
        story.append(Paragraph("• 실시간 탐색된 신규 대형 항공권 특가 소식이 업데이트 대기 중입니다.", body_style))
    story.append(Spacer(1, 3))
    
    # 2. 🌐 [문화 교류] 한국 내 아프리카 행사 & 남아공 내 아시아 행사
    story.append(Paragraph("🌐 [문화/교류] 한국-아프리카 & 남아공-아시아 테마 행사", h2_style))
    if data['exchanges']:
        for item in data['exchanges']:
            story.append(Paragraph(f"• <b>[교류행사]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 수집된 교류 행사를 파싱하고 있습니다.", body_style))
    story.append(Spacer(1, 3))

    # 3. ⚽ [스포츠] 아프리카팀 vs 아시아/한국팀 주요 경합 소식
    story.append(Paragraph("⚽ [스포츠] 아프리카 ↔ 아시아/한국팀 빅매치 & 스포츠 이벤트", h2_style))
    if data['sports']:
        for item in data['sports']:
            story.append(Paragraph(f"• <b>[스포츠매치]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 감지된 양 대륙 간 주요 스포츠 경기 이슈를 파싱 중입니다.", body_style))
    story.append(Spacer(1, 3))

    # 4. 🍷 [미식 축제] K-Food & 남아공 South Africa 미식 축제
    story.append(Paragraph("🍷 [미식 축제] K-Food & 남아공 South Africa 미식 페스티벌", h2_style))
    if data['festivals']:
        for item in data['festivals']:
            story.append(Paragraph(f"• <b>[미식/축제]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 진행 중인 미식 축제 트렌드를 수집 중입니다.", body_style))
    story.append(Spacer(1, 3))
    
    # 5. 🏛️ [MICE] 주요 MICE 행사 & 박람회/컨벤션
    story.append(Paragraph("🏛️ [MICE & 컨벤션] 주요 MICE 행사 및 국제 박람회 소식", h2_style))
    if data['mice']:
        for item in data['mice']:
            story.append(Paragraph(f"• <b>[MICE/박람회]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 관련 MICE 및 포럼 최신 소식이 트래킹 중입니다.", body_style))
    story.append(Spacer(1, 3))
    
    # 6. 🎁 [관광 혜택] 남아공 & 한국 특별 이벤트 및 혜택
    story.append(Paragraph("🎁 [관광 혜택] 한국 · 남아공 관광 이벤트 및 할인 혜택", h2_style))
    if data['promotions']:
        for item in data['promotions']:
            story.append(Paragraph(f"• <b>[이벤트/혜택]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 신규 관광 프로모션을 파싱 중입니다.", body_style))

    # 7. 유튜브 미디어 화제성
    if data['yt_videos']:
        story.append(Spacer(1, 3))
        story.append(Paragraph("▶️ [YouTube 미디어 화제성]", h2_style))
        for vid in data['yt_videos']:
            v_title = vid['snippet']['title']
            story.append(Paragraph(f"• <b>[Shorts/Video]</b> {clean_text(v_title)}", body_style))
            
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def upload_to_gdrive(pdf_bytes, time_str):
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    if not all([client_id, client_secret, refresh_token, folder_id]):
        print("❌ 오류: Google Drive Secrets 중 일부가 누락되었습니다.")
        sys.exit(1)

    folder_id = folder_id.strip().rstrip('/')
    if '?' in folder_id:
        folder_id = folder_id.split('?')
    if '/' in folder_id:
        folder_id = folder_id.split('/')[-1]

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )

    try:
        service = build("drive", "v3", credentials=creds)
        filename = f"StariaPj_Daily_Report_{time_str}_KST.pdf"
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
            "mimeType": "application/pdf"
        }

        media = MediaInMemoryUpload(pdf_bytes, mimetype="application/pdf", resumable=True)

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        print(f"✅ Google Drive PDF 업로드 성공! (파일명: {filename}, ID: {file.get('id')})")

    except Exception as e:
        print(f"❌ Google Drive 업로드 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    report_data = generate_report_data()
    pdf_bytes = create_pdf_bytes(report_data)
    upload_to_gdrive(pdf_bytes, report_data['time_str'])

#새롭게 추가된 카테고리 요약
#✈️ [항공 특가]: 남아공발 한국행 & 한국발 남아공행 특가 프로모션 뉴스 (최상단 빨간색 강조)
#🌐 [문화/교류]: 한국 내 아프리카 테마 행사 & 남아공 내 아시아 테마 행사
#⚽ [스포츠]: 아프리카팀 vs 아시아/한국팀 주요 스포츠 경기 및 빅매치
#🍷 [미식 축제]: K-Food 미식 축제 & 남아공 South Africa 푸드 페스티벌
#🏛️ [MICE & 컨벤션]: 국제 박람회, 컨벤션, 포럼 소식
#🎁 [관광 혜택]: 한국·남아공 무료/할인 이벤트 소식
