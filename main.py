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
        print(f"⚠️ RSS 수집 중 경고 (무시 후 진행): {e}")
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
        print(f"⚠️ YouTube API 호출 중 경고 (무시 후 진행): {e}")
    return []

def generate_report_data():
    """
    뉴스 및 프로모션 수집 데이터 조합
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    # 1) 관광 프로모션 및 혜택 특집 수집 (남아공 & 한국 대상)
    promo_keywords = "(남아공 OR 대한민국 OR 아프리카) (관광 OR 프로모션 OR 이벤트 OR 할인 OR 무료 OR 특가)"
    promo_entries = fetch_google_news_rss(promo_keywords)
    
    # 2) 미디어 화제성 (YouTube & News) 수집
    trend_keywords = "아프리카 미식 관광 K-food"
    trend_entries = fetch_google_news_rss(trend_keywords)
    
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    yt_videos = fetch_youtube_buzz("Africa tourism gastronomy", youtube_api_key)
    
    return {
        'time_str': time_str,
        'now_kst_str': now_kst.strftime('%Y-%m-%d %H:%M:%S'),
        'promotions': promo_entries,
        'trends': trend_entries,
        'yt_videos': yt_videos
    }

def create_pdf_bytes(data):
    """
    수집된 데이터를 바탕으로 고품질 PDF 바이너리 생성
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
        textColor=colors.HexColor('#4A5568'), spaceAfter=12
    )
    h2_style = ParagraphStyle(
        'Heading2', fontName='HYGothic-Medium', fontSize=12, leading=16,
        textColor=colors.HexColor('#2B6CB0'), spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle(
        'BodyCustom', fontName='HYSMyeongJo-Medium', fontSize=9.5, leading=14,
        textColor=colors.HexColor('#2D3748'), spaceAfter=6
    )
    highlight_style = ParagraphStyle(
        'HighlightCustom', fontName='HYGothic-Medium', fontSize=9.5, leading=14,
        textColor=colors.HexColor('#C53030'), spaceAfter=6
    )

    story = []
    
    # 헤더
    story.append(Paragraph("StariaPj 일일 핫이슈 & 관광 프로모션 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | 한국·남아공 특보 연계", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#3182CE'), spaceAfter=12))
    
    # [특집 1] 🎁 남아공 & 한국 관광 특별 이벤트/프로모션 (타전용 1순위)
    story.append(Paragraph("🎁 [특특보] 남아공 & 한국 관광 섹터 특별 이벤트 · 프로모션 소식", h2_style))
    if data['promotions']:
        for item in data['promotions']:
            title = item.title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(f"• <b>[이벤트/혜택]</b> {title}", highlight_style))
    else:
        story.append(Paragraph("• 현재 실시간 감지된 신규 대형 프로모션은 없으며 기본 트렌드가 유지 중입니다.", body_style))
    
    story.append(Spacer(1, 8))
    
    # [특집 2] 🔥 실시간 미디어 통합 화제성 이슈 (Media Buzz)
    story.append(Paragraph("🔥 [화제성 TOP] 실시간 뉴스 및 미디어 트렌드", h2_style))
    if data['trends']:
        for item in data['trends']:
            title = item.title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(f"• <b>[뉴스 화제]</b> {title}", body_style))
    else:
        story.append(Paragraph("• 수집된 실시간 미디어 이슈를 파싱 중입니다.", body_style))

    # 유튜브 화제성 (API 키 설정 시 자동 노출)
    if data['yt_videos']:
        story.append(Spacer(1, 4))
        story.append(Paragraph("▶️ [YouTube 바이럴 영상 반응도]", h2_style))
        for vid in data['yt_videos']:
            v_title = vid['snippet']['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(f"• <b>[Shorts/Video]</b> {v_title}", body_style))
            
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
