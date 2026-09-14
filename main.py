import io
import os
import sys
import json
import requests
import feedparser
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# 1. ReportLab 내장 한글 폰트 등록
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

def get_gdrive_service():
    """Google Drive API 서비스 객체 생성"""
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )
    return build("drive", "v3", credentials=creds)

def load_gdrive_cache(service, folder_id):
    """
    구글 드라이브에서 이전 수집 캐시(latest_news_cache.json)를 불러와 24시간 이내 소식을 이월
    """
    if not service or not folder_id:
        return {}
    try:
        results = service.files().list(
            q=f"'{folder_id}' in parents and name='latest_news_cache.json' and trashed=false",
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        if not files:
            return {}
        
        file_id = files[0]['id']
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        return json.loads(fh.read().decode('utf-8'))
    except Exception as e:
        print(f"⚠️ 캐시 파일 읽기 경고 (무시 후 계속 진행): {e}")
        return {}

def save_gdrive_cache(service, folder_id, cache_data):
    """
    이번에 수집/유지된 최신 24시간 소식을 구글 드라이브 캐시(latest_news_cache.json)로 갱신 저장
    """
    if not service or not folder_id:
        return
    try:
        json_bytes = json.dumps(cache_data, ensure_ascii=False, indent=2).encode('utf-8')
        media = MediaInMemoryUpload(json_bytes, mimetype="application/json", resumable=True)
        
        results = service.files().list(
            q=f"'{folder_id}' in parents and name='latest_news_cache.json' and trashed=false",
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        
        if files:
            file_id = files[0]['id']
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {
                "name": "latest_news_cache.json",
                "parents": [folder_id],
                "mimeType": "application/json"
            }
            service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        print("✅ 구글 드라이브 최신 데이터 캐시(latest_news_cache.json) 동기화 완료!")
    except Exception as e:
        print(f"⚠️ 캐시 파일 저장 경고: {e}")

def upload_json_to_gdrive(service, folder_id, cache_data, time_str):
    """
    독립된 날짜별 JSON 데이터 파일(StariaPj_Daily_Data_YYYY-MM-DD_HHMM_KST.json) 구글 드라이브 추가 업로드
    """
    if not service or not folder_id:
        return
    try:
        filename = f"StariaPj_Daily_Data_{time_str}_KST.json"
        json_bytes = json.dumps(cache_data, ensure_ascii=False, indent=2).encode('utf-8')
        media = MediaInMemoryUpload(json_bytes, mimetype="application/json", resumable=True)
        
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
            "mimeType": "application/json"
        }
        file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        print(f"✅ Google Drive 독립 JSON 데이터 파일 업로드 성공! (파일명: {filename}, ID: {file.get('id')})")
    except Exception as e:
        print(f"⚠️ JSON 데이터 파일 업로드 실패: {e}")

def fetch_google_news_rss_realtime(query):
    """Google News RSS 최신 24시간 항목 수집"""
    realtime_query = f"{query} when:1d"
    encoded_query = urllib.parse.quote(realtime_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    
    entries = []
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            now_utc = datetime.now(timezone.utc)
            for entry in feed.entries:
                pub_ts = now_utc.timestamp()
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    pub_ts = pub_dt.timestamp()
                
                entries.append({
                    'title': entry.title,
                    'link': getattr(entry, 'link', ''),
                    'pub_ts': pub_ts
                })
    except Exception as e:
        print(f"⚠️ RSS 수집 경고 ({query}): {e}")
    return entries

def fetch_youtube_buzz(query, youtube_api_key):
    """YouTube Data API를 활용한 최근 24시간 반응 수집"""
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
        print(f"⚠️ YouTube API 경고: {e}")
    return []

def merge_and_filter_entries(new_entries, cached_entries, max_hours=24):
    """
    24시간 이내 소식 이월 유지 로직
    """
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff_ts = now_ts - (max_hours * 3600)
    
    combined_dict = {}
    
    for c in cached_entries:
        if c.get('pub_ts', 0) >= cutoff_ts:
            combined_dict[c['title']] = c
            
    for n in new_entries:
        if n.get('pub_ts', 0) >= cutoff_ts:
            combined_dict[n['title']] = n
            
    sorted_items = sorted(combined_dict.values(), key=lambda x: x['pub_ts'], reverse=True)
    return sorted_items[:5]

def clean_text(text):
    """ReportLab XML 파싱 오류 방지"""
    if not text:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def select_top_shorts_topics(data):
    """실제 소식지 내 수집 데이터로만 파급력 순 Shorts TOP 3 선별"""
    candidates = []
    seen_titles = set()
    
    def add_candidates(items, category, reason_fmt, hook_fmt, script_fmt):
        for item in items:
            title = item['title']
            if title in seen_titles:
                continue
            seen_titles.add(title)
            candidates.append({
                'category': category,
                'title': title,
                'reason': reason_fmt,
                'hook': hook_fmt,
                'script': script_fmt
            })

    add_candidates(data.get('breaking', []), '🚨 긴급/속보 파급', 
                   '남아공 & 한국 국민의 안전/제도/삶에 직접 영향을 미치는 실시간 속보',
                   '"잠깐! 남아공과 한국에서 지금 난리 난 이 소식, 알고 계셨나요?"',
                   '[0~3초] 속보 자막 & 멘트 → [3~20초] 24시간 내 발생 사건 핵심 요약 → [20~30초] "여러분의 생각은?" 댓글 유도')

    add_candidates(data.get('flights', []), '✈️ 파격 특가/혜택',
                   '양국 간 이동 비용 절감 및 실질적 혜택이 매우 높아 바이럴 유력',
                   '"남아공-한국 비행기표 실화? 24시간 안에 나온 이 특가 혜택 놓치면 손해입니다!"',
                   '[0~3초] 할인 금액 강조 → [3~20초] 프로모션 조건 및 일시 빠르게 전달 → [20~30초] "주변에 남아공 갈 사람 태그!"')

    add_candidates(data.get('exchanges', []) + data.get('sports', []), '🌐 교류/스포츠 매치',
                   '아프리카/남아공과 한국 간 대중적 관심도 및 시청 지속 시간이 높은 이슈',
                   '"아프리카와 한국이 만났다! 양국 대중을 뜨겁게 달군 실시간 현장 소식!"',
                   '[0~3초] 현장/하이라이트 장면 → [3~20초] 주요 기사 내용 및 반응 정리 → [20~30초] "여러분의 의견을 댓글로 들려주세요!"')

    add_candidates(data.get('festivals', []) + data.get('promotions', []), '🍷 미식/관광 페스티벌',
                   'K-Food 및 남아공 특색이 살아있어 영상 제작 시 시각적 바이럴이 높은 소재',
                   '"이 조합 미쳤다! 현지인들도 줄 서서 먹는 현장 바이럴 소식!"',
                   '[0~3초] 미식 클로즈업 → [3~20초] 페스티벌 및 인기 메뉴 3가지 소개 → [20~30초] "가장 먹고 싶은 것은?" 댓글 축제')

    return candidates[:3]

def generate_report_data(service, folder_id):
    """데이터 수집 및 이월 캐시 병합"""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    old_cache = load_gdrive_cache(service, folder_id)
    new_cache = {}
    
    queries = {
        'breaking': '(남아공 OR 아프리카 OR "South Africa") (속보 OR 긴급 OR 특종 OR 사건 OR 사고 OR 비상 OR "breaking news") -축구 -게임',
        'flights': '(남아공 OR "South Africa") (항공권 OR 비행기표 OR "flight ticket" OR "airfare") (특가 OR 프로모션 OR 할인 OR "discount") -무인 -LIG -밀코르 -축구 -배달 -특급',
        'exchanges': '((한국 OR 대한민국) (남아공 OR 아프리카) (문화제 OR 교류 OR "cultural exchange")) OR ((남아공 OR "South Africa") (한국 OR "Korea") (행사 OR 축제 OR "festival")) -아시안게임 -축구 -경기',
        'sports': '(아프리카 OR 남아공 OR "South Africa") (한국 OR 대한민국 OR "Korea") (맞대결 OR 평가전 OR 친선전 OR 대표팀 OR "vs") (축구 OR 농구 OR 야구) -아시안게임 -유로 -올림픽',
        'festivals': '("K-Food" OR 남아공 OR "South Africa") (미식 OR "gastro" OR "food festival") (축제 OR 페스티벌)',
        'mice': '(남아공 OR 대한민국 OR 아프리카) (MICE OR 박람회 OR 컨벤션 OR 포럼 OR "exhibition")',
        'promotions': '(남아공 OR 대한민국 OR 아프리카) (관광 OR "tourism") (프로모션 OR 이벤트 OR 할인 OR 무료) -배달'
    }
    
    report_data = {
        'time_str': time_str,
        'now_kst_str': now_kst.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    for key, query in queries.items():
        raw_entries = fetch_google_news_rss_realtime(query)
        cached_entries = old_cache.get(key, [])
        merged = merge_and_filter_entries(raw_entries, cached_entries, max_hours=24)
        report_data[key] = merged
        new_cache[key] = merged
        
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    report_data['yt_videos'] = fetch_youtube_buzz("South Africa Korea travel flight deals food festival", youtube_api_key)
    
    report_data['shorts_top3'] = select_top_shorts_topics(report_data)
    report_data['new_cache'] = new_cache
    
    return report_data

def create_pdf_bytes(data):
    """PDF 리포트 생성"""
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
    
    story.append(Paragraph("StariaPj 온타임 24시간 긴급속보 & Shorts 제작 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | 최근 24시간 유효 소식 및 Shorts 추천", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#6B46C1'), spaceAfter=10))
    
    story.append(Paragraph("🎬 [필수 제작] 지금 당장 쇼츠(Shorts)로 만들어야 하는 주제 TOP 3", shorts_h2_style))
    if data['shorts_top3']:
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
    else:
        story.append(Paragraph("• 최근 24시간 이내 수집된 소식지 내용 중 별도 추천할 파급 이슈가 없습니다. (Blank 유지)", empty_style))
        
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#CBD5E0'), spaceAfter=8))
    
    sections = [
        ('breaking', '🚨 [실시간 긴급 속보] 남아공 · 아프리카 · 한국 관련 주요 사건/사고', True),
        ('flights', '✈️ [항공 특가] 한국 ↔ 남아공 24HR 특가 항공권 & 프로모션', True),
        ('exchanges', '🌐 [문화/교류] 한국-아프리카 & 남아공-한국 테마 행사 소식', False),
        ('sports', '⚽ [스포츠] 아프리카 ↔ 한국 대표팀 24HR 매치 & 스포츠 이벤트', False),
        ('festivals', '🍷 [미식 축제] K-Food & 남아공 South Africa 미식 페스티벌', False),
        ('mice', '🏛️ [MICE & 컨벤션] 주요 MICE 행사 및 국제 박람회 소식', False),
        ('promotions', '🎁 [관광 혜택] 한국 · 남아공 관광 이벤트 및 할인 혜택', False)
    ]
    
    for key, sec_title, is_alert in sections:
        story.append(Paragraph(sec_title, h2_style))
        items = data.get(key, [])
        if items:
            for item in items:
                prefix = "• <b>[속보]</b> " if key == 'breaking' else ("• <b>[특가]</b> " if key == 'flights' else "• ")
                style = alert_style if is_alert else body_style
                story.append(Paragraph(f"{prefix}{clean_text(item['title'])}", style))
        else:
            story.append(Paragraph("• 최근 24시간 이내 등록되거나 유효한 소식이 없습니다.", empty_style))
        story.append(Spacer(1, 3))

    if data['yt_videos']:
        story.append(Spacer(1, 3))
        story.append(Paragraph("▶️ [YouTube 24HR 바이럴 영상]", h2_style))
        for vid in data['yt_videos']:
            v_title = vid['snippet']['title']
            story.append(Paragraph(f"• <b>[Shorts/Video]</b> {clean_text(v_title)}", body_style))
            
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()

def upload_to_gdrive(service, folder_id, pdf_bytes, time_str):
    """구글 드라이브 PDF 파일 업로드"""
    if not service or not folder_id:
        print("❌ 구글 드라이브 설정이 누락되었습니다.")
        sys.exit(1)

    try:
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
    folder_id = os.environ.get("GDRIVE_FOLDER_ID", "").strip().rstrip('/')
    if '?' in folder_id:
        folder_id = folder_id.split('?')
    if '/' in folder_id:
        folder_id = folder_id.split('/')[-1]

    service = get_gdrive_service()
    report_data = generate_report_data(service, folder_id)
    pdf_bytes = create_pdf_bytes(report_data)
    
    # 1. PDF 리포트 파일 업로드
    upload_to_gdrive(service, folder_id, pdf_bytes, report_data['time_str'])
    
    # 2. 독립된 JSON 데이터 파일 업로드 (StariaPj_Daily_Data_YYYY-MM-DD_HHMM_KST.json)
    upload_json_to_gdrive(service, folder_id, report_data['new_cache'], report_data['time_str'])
    
    # 3. 이월용 최신 캐시 파일(latest_news_cache.json) 갱신
    save_gdrive_cache(service, folder_id, report_data['new_cache'])
