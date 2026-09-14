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

# 1. ReportLab 내장 한글 폰트 등록 (한글 깨짐 차단)
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

def fetch_google_news_rss_realtime(query, max_hours=24):
    """
    Google News RSS에서 최근 24시간 이내 발행된 '실시간(On-Time)' 최신 기사만 파싱
    """
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
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if now_utc - pub_dt > timedelta(hours=max_hours):
                        continue  # 3~4일 전 지나간 소식 차단
                
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

def select_top_shorts_topics(data):
    """
    수집된 24시간 실시간 데이터 중 남아공-한국 국민에게 파급력(Impact)이 가장 큰
    Shorts 제작 추천 주제 TOP 3 및 3초 Hook 멘트, 30초 대본 개요 자동 생성
    """
    candidates = []
    
    # 1순위: 긴급 속보 / 사건 사고 (양국 국민의 삶에 직접적 파급력 최상)
    for item in data.get('breaking', []):
        candidates.append({
            'category': '🚨 긴급/속보 파급',
            'title': item.title,
            'reason': '남아공 & 한국 국민의 안전/제도/삶에 직접 영향을 미치는 실시간 속보',
            'hook': f'"잠깐! 남아공과 한국에서 지금 난리 난 이 소식, 알고 계셨나요?"',
            'script': '[0~3초] 속보 자막 & 멘트 → [3~20초] 24시간 내 발생 사건 핵심 요약 → [20~30초] "여러분의 생각은?" 댓글 유도'
        })
        
    # 2순위: 파격 항공 특가 / 대형 혜택 (양국 체류/이동 비용 직결)
    for item in data.get('flights', []):
        candidates.append({
            'category': '✈️ 파격 특가/혜택',
            'title': item.title,
            'reason': '양국 간 이동 비용 절감 및 실질적 혜택이 매우 높아 바이럴 유력',
            'hook': f'"남아공-한국 비행기표 실화? 24시간 안에 나온 이 특가 혜택 놓치면 손해입니다!"',
            'script': '[0~3초] 할인 금액 강조 → [3~20초] 프로모션 조건 및 일시 빠르게 전달 → [20~30초] "주변에 남아공 갈 사람 태그!"'
        })
        
    # 3순위: 문화 교류 및 스포츠 매치 (대중적 열광 & 공감대)
    for item in data.get('exchanges', []) + data.get('sports', []):
        candidates.append({
            'category': '🌐 교류/스포츠 매치',
            'title': item.title,
            'reason': '양국 대중이 동시에 주목하며 시청 지속 시간이 높은 이슈',
            'hook': f'"남아공과 한국이 만났다! 양국 대중을 뜨겁게 달군 현장 공개!"',
            'script': '[0~3초] 하이라이트 영상 → [3~20초] 주요 기사 내용 및 현지 반응 정리 → [20~30초] "누가 승자가 될까요?" 투표 유도'
        })
        
    # 4순위: 미식 축제 및 관광 혜택 (시각적 흥미)
    for item in data.get('festivals', []) + data.get('promotions', []):
        candidates.append({
            'category': '🍷 미식/관광 페스티벌',
            'title': item.title,
            'reason': 'K-Food 및 남아공 특색이 살아있어 영상 제작 시 시각적 바이럴이 높은 소재',
            'hook': f'"이 조합 미쳤다! 현지인들도 줄 서서 먹는 현장 바이럴 소식!"',
            'script': '[0~3초] 미식 클로즈업 → [3~20초] 페스티벌 및 인기 메뉴 3가지 소개 → [20~30초] "가장 먹고 싶은 것은?" 댓글 축제'
        })
        
    selected = candidates[:3]
    
    # 만약 수집된 24시간 뉴스가 3개 미만일 경우 기본 가이드 항목으로 자동 보충
    default_fallbacks = [
        {
            'category': '🔥 미식 트렌드',
            'title': '남아공 현지 K-Food 열풍 및 한국 미식 문화 현황',
            'reason': '양국 미식 교류 반응과 시각적 흥미도가 높은 숏츠 소재',
            'hook': '"남아공 사람들도 줄 서서 먹는 한국 음식? 현지 반응이 진짜 대박입니다!"',
            'script': '[0~3초] 현지 반응 컷 → [3~20초] 인기 K-Food 3가지와 반응 전달 → [20~30초] "다음 미식 핫플은 어디?" 댓글 유도'
        },
        {
            'category': '✈️ 여행 꿀팁',
            'title': '한국 ↔ 남아공 최단 비행 노선 및 항공권 예매 팁',
            'reason': '양국 방문객들이 가장 궁금해하는 실용 정보 숏츠',
            'hook': '"남아공 갈 때 비행기표 가장 싸게 구하는 법! 이 3까지만 기억하세요!"',
            'script': '[0~3초] 예매 자막 → [3~20초] 최단시간/최저가 예매 팁 3단계 → [20~30초] "저장해두고 남아공 갈 때 꺼내보세요!"'
        },
        {
            'category': '🇿🇦🇰🇷 핫이슈',
            'title': '남아공 & 한국 현지에서 지금 가장 화제인 관광 현장',
            'reason': '실시간 바이럴 요소가 풍부한 글로벌 이슈',
            'hook': '"지금 남아공과 한국에서 동시 폭발 중인 역대급 핫플을 공개합니다!"',
            'script': '[0~3초] 핫플 전경 → [3~20초] 실시간 반응 및 핵심 포인트 3가지 → [20~30초] "함께 가고 싶은 친구에게 공유하기!"'
        }
    ]
    
    while len(selected) < 3:
        selected.append(default_fallbacks[len(selected)])
        
    return selected

def generate_report_data():
    """
    최근 24시간 이내 실시간(On-time) 특종/사고/특가/이벤트 데이터 수집
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    # 1) 🚨 실시간 긴급 속보
    breaking_query = '(남아공 OR 아프리카 OR "South Africa") (속보 OR 긴급 OR 특종 OR 사건 OR 사고 OR 비상 OR "breaking news") -축구 -게임'
    breaking_entries = fetch_google_news_rss_realtime(breaking_query)
    
    # 2) ✈️ 24시간 이내 여객 항공 특가
    flight_query = '(남아공 OR "South Africa") (항공권 OR 비행기표 OR "flight ticket" OR "airfare") (특가 OR 프로모션 OR 할인 OR "discount") -무인 -LIG -밀코르 -축구 -배달 -특급'
    flight_entries = fetch_google_news_rss_realtime(flight_query)
    
    # 3) 🌐 아프리카 ↔ 아시아/한국 문화 교류 행사
    exchange_query = '((한국 OR 대한민국) 아프리카 (문화제 OR 교류 OR "cultural exchange")) OR ((남아공 OR "South Africa") (아시아 OR 한국) (행사 OR 축제 OR "festival")) -축구 -경기'
    exchange_entries = fetch_google_news_rss_realtime(exchange_query)
    
    # 4) ⚽ 스포츠 빅매치
    sports_query = '(아프리카 OR 남아공 OR "South Africa") (아시아 OR 한국 OR "Korea") (대표팀 OR 매치 OR "match" OR "tournament") (축구 OR 야구 OR 농구)'
    sports_entries = fetch_google_news_rss_realtime(sports_query)
    
    # 5) 🍷 미식 축제
    gastro_query = '("K-Food" OR 남아공 OR "South Africa") (미식 OR "gastro" OR "food festival") (축제 OR 페스티벌)'
    gastro_entries = fetch_google_news_rss_realtime(gastro_query)
    
    # 6) 🏛️ MICE 행사
    mice_query = '(남아공 OR 대한민국 OR 아프리카) (MICE OR 박람회 OR 컨벤션 OR 포럼 OR "exhibition")'
    mice_entries = fetch_google_news_rss_realtime(mice_query)
    
    # 7) 🎁 관광 프로모션 및 혜택
    promo_query = '(남아공 OR 대한민국 OR 아프리카) (관광 OR "tourism") (프로모션 OR 이벤트 OR 할인 OR 무료) -배달'
    promo_entries = fetch_google_news_rss_realtime(promo_query)
    
    # 8) YouTube 최근 24시간 실시간 트렌드
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    yt_videos = fetch_youtube_buzz("South Africa Korea travel flight deals food festival", youtube_api_key)
    
    raw_data = {
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
    
    # 파급력 및 숏츠 대본 가이드 포함 TOP 3 선정
    raw_data['shorts_top3'] = select_top_shorts_topics(raw_data)
    return raw_data

def create_pdf_bytes(data):
    """
    Shorts 추천 TOP 3 (3초 Hook & 30초 대본 포함) 및 24HR 실시간 특보 반영 PDF 생성
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
    shorts_h2_style = ParagraphStyle(
        'ShortsH2', fontName='HYGothic-Medium', fontSize=12, leading=16,
        textColor=colors.HexColor('#6B46C1'), spaceBefore=4, spaceAfter=6
    )
    body_style = ParagraphStyle(
        'BodyCustom', fontName='HYSMyeongJo-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#2D3748'), spaceAfter=4
    )
    shorts_body_style = ParagraphStyle(
        'ShortsBody', fontName='HYSMyeongJo-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#2C5282'), spaceAfter=3
    )
    alert_style = ParagraphStyle(
        'AlertCustom', fontName='HYGothic-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#C53030'), spaceAfter=3
    )
    empty_style = ParagraphStyle(
        'EmptyCustom', fontName='HYSMyeongJo-Medium', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#718096'), spaceAfter=3
    )

    story = []
    
    # 헤더
    story.append(Paragraph("StariaPj 온타임 24시간 긴급속보 & Shorts 제작 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | 🎬 3초 Hook & 30초 대본 개요 포함", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#6B46C1'), spaceAfter=10))
    
    # 🎬 [최상단 전용] 당장 제작해야 할 Shorts 추천 주제 TOP 3 (후킹 & 대본 포함)
    story.append(Paragraph("🎬 [필수 제작] 지금 당장 쇼츠(Shorts)로 만들어야 하는 주제 TOP 3", shorts_h2_style))
    for idx, item in enumerate(data['shorts_top3'], 1):
        clean_t = clean_text(item['title'])
        clean_r = clean_text(item['reason'])
        clean_hk = clean_text(item.get('hook', ''))
        clean_sc = clean_text(item.get('script', ''))
        
        story.append(Paragraph(f"<b>{idx}. [{item['category']}]</b> {clean_t}", alert_style if '🚨' in item['category'] else shorts_body_style))
        story.append(Paragraph(f"   └ 💡 <b>추천 이유:</b> <i>{clean_r}</i>", empty_style))
        story.append(Paragraph(f"   └ 🎯 <b>3초 Hook 멘트:</b> <font color='#C53030'><b>{clean_hk}</b></font>", body_style))
        story.append(Paragraph(f"   └ ⏱️ <b>30초 대본 개요:</b> {clean_sc}", empty_style))
        story.append(Spacer(1, 4))
        
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#CBD5E0'), spaceAfter=8))
    
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
