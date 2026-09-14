import io
import os
import sys
import requests
import feedparser
import urllib.parse
from datetime import datetime, timedelta, timezone
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

# 1. ReportLab 내장 한글 폰트 등록 (깨짐 방지)
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

def fetch_google_news_rss_realtime(query, max_hours=24):
    """
    Google News RSS에서 최근 24시간 이내 발행된 '실시간(On-Time)' 최신 기사만 파싱
    """
    # 1차 필터링: 검색어에 'when:1d' 결합 (최근 24시간 이내 기사)
    realtime_query = f"{query} when:1d"
    encoded_query = urllib.parse.quote(realtime_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            valid_entries = []
            now_utc = datetime.now(timezone.utc)
            
            for entry in feed.entries:
                # 2차 검증: 실제 발행 시각(published_parsed) 기준 24시간 초과 기사는 차단
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if now_utc - pub_dt > timedelta(hours=max_hours):
                        continue  # 3~4일 전 구형 기사 자동 패스
                
                valid_entries.append(entry)
                if len(valid_entries) >= 5:
                    break
            return valid_entries
    except Exception as e:
        print(f"⚠️ RSS 실시간 수집 경고 (키워드: {query}): {e}")
    return []

def fetch_youtube_buzz(query, youtube_api_key):
    """
    YouTube Data API를 활용한 최근 24시간 바이럴 영상 반응 수집
    """
    if not youtube_api_key:
        return []
    
    url = "https://www.googleapis.com/youtube/v3/search"
    published_after = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    
    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'order': 'date',
        'publishedAfter': published_after,
        'maxResults': 3,
        'key': youtube_api_key
    }
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            return data.get('items', [])
    except Exception as e:
        print(f"⚠️ YouTube API 호출 경고: {e}")
    return []

def clean_text(text):
    """ReportLab XML 파싱 오류 방지를 위한 태그 특수문자 치환"""
    if not text:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def generate_report_data():
    """
    최근 24시간 이내 실시간(On-time) 특종/사고/특가/이벤트 데이터 수집
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    # 1) 🚨 실시간 긴급 속보 (사건/사고/비상)
    breaking_query = '(남아공 OR 아프리카 OR "South Africa") (속보 OR 긴급 OR 특종 OR 사건 OR 사고 OR 비상 OR "breaking news") -축구 -게임'
    breaking_entries = fetch_google_news_rss_realtime(breaking_query)
    
    # 2) ✈️ 24시간 이내 여객 항공 특가 (군사/무인항공/스포츠/배달 노이즈 제거)
    flight_query = '(남아공 OR "South Africa") (항공권 OR 비행기표 OR "flight ticket" OR "airfare") (특가 OR 프로모션 OR 할인 OR "discount") -무인 -LIG -밀코르 -축구 -배달 -특급'
    flight_entries = fetch_google_news_rss_realtime(flight_query)
    
    # 3) 🌐 아프리카 ↔ 아시아/한국 문화 교류 행사
    exchange_query = '((한국 OR 대한민국) 아프리카 (문화제 OR 교류 OR "cultural exchange")) OR ((남아공 OR "South Africa") (아시아 OR 한국) (행사 OR 축제 OR "festival")) -축구 -경기'
    exchange_entries = fetch_google_news_rss_realtime(exchange_query)
    
    # 4) ⚽ 스포츠 빅매치 (아프리카팀 ↔ 아시아/한국 대표팀)
    sports_query = '(아프리카 OR 남아공 OR "South Africa") (아시아 OR 한국 OR "Korea") (대표팀 OR 매치 OR "match" OR "tournament") (축구 OR 야구 OR 농구)'
    sports_entries = fetch_google_news_rss_realtime(sports_query)
    
    # 5) 🍷 미식 축제 (K-Food & 남아공 South Africa 미식 페스티벌)
    gastro_query = '("K-Food" OR 남아공 OR "South Africa") (미식 OR "gastro" OR "food festival") (축제 OR 페스티벌)'
    gastro_entries = fetch_google_news_rss_realtime(gastro_query)
    
    # 6) 🏛️ MICE 행사 (컨벤션, 박람회, 포럼)
    mice_query = '(남아공 OR 대한민국 OR 아프리카) (MICE OR 박람회 OR 컨벤션 OR 포럼 OR "exhibition")'
    mice_entries = fetch_google_news_rss_realtime(mice_query)
    
    # 7) 🎁 관광 프로모션 및 혜택
    promo_query = '(남아공 OR 대한민국 OR 아프리카) (관광 OR "tourism") (프로모션 OR 이벤트 OR 할인 OR 무료) -배달'
    promo_entries = fetch_google_news_rss_realtime(promo_query)
    
    # 8) YouTube 최근 24시간 실시간 트렌드
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    yt_videos = fetch_youtube_buzz("South Africa Korea travel flight deals food festival", youtube_api_key)
    
    return {
        'time_str': time_str,
        'now_kst_str': now_kst.strftime('%Y-%m-%d %H:%M:%S'),
        'breaking': breaking_entries,
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
    실시간(On-time) 24시간 특보 반영 PDF 바이너리 생성
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
    empty_style = ParagraphStyle(
        'EmptyCustom', fontName='HYSMyeongJo-Medium', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#718096'), spaceAfter=4
    )

    story = []
    
    # 헤더
    story.append(Paragraph("StariaPj 온타임 24시간 긴급속보 & 트렌드 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | 최근 24시간 이내 실시간(On-Time) 수집 전용", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#E53E3E'), spaceAfter=8))
    
    # 1. 🚨 [실시간 긴급 속보]
    story.append(Paragraph("🚨 [실시간 긴급 속보] 남아공 · 아프리카 · 한국 관련 주요 사건/사고", h2_style))
    if data['breaking']:
        for item in data['breaking']:
            story.append(Paragraph(f"• <b>[속보]</b> {clean_text(item.title)}", alert_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 감지된 신규 긴급 속보가 없습니다. (정상 모니터링 중)", empty_style))
    story.append(Spacer(1, 3))

    # 2. ✈️ [항공 특가]
    story.append(Paragraph("✈️ [항공 특가] 한국 ↔ 남아공 24HR 신규 특가 항공권 & 프로모션", h2_style))
    if data['flights']:
        for item in data['flights']:
            story.append(Paragraph(f"• <b>[특가소식]</b> {clean_text(item.title)}", alert_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 신규 등록된 대형 항공권 특가가 없습니다.", empty_style))
    story.append(Spacer(1, 3))
    
    # 3. 🌐 [문화/교류]
    story.append(Paragraph("🌐 [문화/교류] 한국-아프리카 & 남아공-아시아 테마 행사 소식", h2_style))
    if data['exchanges']:
        for item in data['exchanges']:
            story.append(Paragraph(f"• <b>[교류행사]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 업데이트된 신규 교류 행사가 없습니다.", empty_style))
    story.append(Spacer(1, 3))

    # 4. ⚽ [스포츠]
    story.append(Paragraph("⚽ [스포츠] 아프리카 ↔ 아시아/한국팀 24HR 매치 & 스포츠 이벤트", h2_style))
    if data['sports']:
        for item in data['sports']:
            story.append(Paragraph(f"• <b>[스포츠매치]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 발생한 주요 스포츠 경기 이슈가 없습니다.", empty_style))
    story.append(Spacer(1, 3))

    # 5. 🍷 [미식 축제]
    story.append(Paragraph("🍷 [미식 축제] K-Food & 남아공 South Africa 미식 페스티벌", h2_style))
    if data['festivals']:
        for item in data['festivals']:
            story.append(Paragraph(f"• <b>[미식/축제]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 수집된 신규 미식 축제 소식이 없습니다.", empty_style))
    story.append(Spacer(1, 3))
    
    # 6. 🏛️ [MICE]
    story.append(Paragraph("🏛️ [MICE & 컨벤션] 주요 MICE 행사 및 국제 박람회 소식", h2_style))
    if data['mice']:
        for item in data['mice']:
            story.append(Paragraph(f"• <b>[MICE/박람회]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 신규 MICE 공시가 없습니다.", empty_style))
    story.append(Spacer(1, 3))
    
    # 7. 🎁 [관광 혜택]
    story.append(Paragraph("🎁 [관광 혜택] 한국 · 남아공 관광 이벤트 및 할인 혜택", h2_style))
    if data['promotions']:
        for item in data['promotions']:
            story.append(Paragraph(f"• <b>[이벤트/혜택]</b> {clean_text(item.title)}", body_style))
    else:
        story.append(Paragraph("• 최근 24시간 이내 발표된 신규 관광 이벤트가 없습니다.", empty_style))

    # 8. 유튜브 미디어 화제성
    if data['yt_videos']:
        story.append(Spacer(1, 3))
        story.append(Paragraph("▶️ [YouTube 24HR 바이럴 영상]", h2_style))
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
        folder_id = folder_id.split('?')[0]
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
