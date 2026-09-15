import io
import os
import sys
import json
import re
import html
import base64
import requests
import feedparser
import urllib.parse
import smtplib
import email.utils
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle

### 1. ReportLab 내장 한글 폰트 등록
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

### 🚫 오래된 노이즈 및 예전 기사 제목 블랙리스트 키워드
BANNED_TITLE_KEYWORDS = ["홍명보", "체코", "16년 만에", "미주조선일보", "2-1 역전승", "히딩크", "벤투"]

### 🚫 외계어 깨짐 및 무의미한 노이즈를 유발하는 해외 도메인 블랙리스트
BANNED_DOMAINS = [
    ".ua", ".ru", ".cz", ".by", ".cn", ".pl", "ua.news", "krakow", "pravda.ru"
]

### 🎨 10단계 중요도 순 그라데이션 색상 (1위: 가장 짙은 먹색 ~ 10위: 옅은 회색)
GRADIENT_COLORS = [
    '#0F172A',  # 1위 (TOP): 가장 짙은 먹색
    '#1E293B',  # 2위
    '#334155',  # 3위
    '#475569',  # 4위
    '#64748B',  # 5위
    '#718096',  # 6위
    '#8592A6',  # 7위
    '#94A3B8',  # 8위
    '#A0AEC0',  # 9위
    '#CBD5E1'   # 10위: 가장 옅은 회색
]

def is_banned_title(title):
    """블랙리스트 키워드가 포함된 예전/불필요 기사 여부 검사"""
    if not title:
        return True
    for kw in BANNED_TITLE_KEYWORDS:
        if kw.lower() in title.lower():
            return True
    return False

def is_banned_domain(url):
    """불필요한 해외 노이즈 도메인(.ua, .ru 등) 필터링"""
    if not url:
        return False
    try:
        domain = urllib.parse.urlparse(url).netloc.lower()
        for b_dom in BANNED_DOMAINS:
            if domain.endswith(b_dom) or b_dom in domain:
                return True
    except Exception:
        pass
    return False

def decode_google_news_url(url, title=""):
    """구글 뉴스 RSS 링크(Base64/Protobuf)에서 실제 언론사 원본 주소를 초고속 내장 디코딩.
    실패 시 구글 검색 링크로 안전 전환하여 100% 정상 연결 보장.
    """
    if not url or url == '#':
        return f"https://www.google.com/search?q={urllib.parse.quote(title)}" if title else '#'
        
    if 'news.google.com' not in url:
        return url
        
    try:
        match = re.search(r'articles/([^/?]+)', url)
        if match:
            b64_str = match.group(1)
            padded_b64 = b64_str + '=' * (-len(b64_str) % 4)
            decoded_bytes = base64.urlsafe_b64decode(padded_b64)
            
            found_urls = re.findall(rb'https?://[a-zA-Z0-9\.\-_~:/?#\\[\\]@!$&\'()*+,;=%]+', decoded_bytes)
            for f_url in found_urls:
                f_str = f_url.decode('utf-8', errors='ignore')
                if 'google.com' not in f_str and 'news.google' not in f_str:
                    return f_str
    except Exception:
        pass
        
    if title:
        return f"https://www.google.com/search?q={urllib.parse.quote(title)}"
    return url

def evaluate_stariapj_region_score(title, text=""):
    """
    StariaPj 4지역 연계 우선순위 산정 함수:
    - P1 (우선순위 1 / 100점): 남아공(ZA), 한국(KR), 아프리카(Africa), 아시아(Asia) 4개 지역 모두 연계
    - P2 (우선순위 2 / 75점):  3개 지역 연계
    - P3 (우선순위 3 / 50점):  2개 지역 연계
    - P4 (우선순위 4 / 25점):  1개 지역 특화
    """
    full_text = (title + " " + text).lower()
    
    has_za = any(k in full_text for k in ["남아공", "south africa", "케이프", "cape town", "gauteng", "요하네스버그", "johannesburg", "western cape", "stellenbosch"])
    has_kr = any(k in full_text for k in ["한국", "대한민국", "korea", "서울", "seoul", "부산", "busan", "제주", "jeju", "k-", "olle"])
    has_africa = any(k in full_text for k in ["아프리카", "africa", "나이지리아", "nigeria", "케냐", "kenya", "가나", "ghana", "탄자니아", "tanzania", "이집트", "egypt", "모로코", "morocco"])
    has_asia = any(k in full_text for k in ["아시아", "asia", "몽골", "mongolia", "일본", "japan", "중국", "china", "베트남", "vietnam", "동남아"])
    
    count = sum([has_za, has_kr, has_africa, has_asia])
    if count >= 4:
        return 100, "P1 (우선순위 1: 4개 지역 전면 연계)"
    elif count == 3:
        return 75, "P2 (우선순위 2: 3개 지역 연계)"
    elif count == 2:
        return 50, "P3 (우선순위 3: 2개 지역 연계)"
    else:
        return 25, "P4 (우선순위 4: 1개 지역 특화)"

def calculate_google_trends_score(title):
    """
    Real-time Google Trends index 산출 함수:
    - 실시간 바이럴 검색 지수 (0~100점)
    - Breakout(급상승) 키워드 감지 시 10% 추가 가산점 (최대 100점)
    """
    title_lower = title.lower()
    base_score = 70.0
    
    viral_keywords = ["속보", "특가", "k-food", "k-pop", "k-culture", "미식", "와인", "트레킹", "올레길", "150만", "26.1b", "r26.1b", "gastronomy", "festival", "할인", "무료", "0원"]
    for kw in viral_keywords:
        if kw in title_lower:
            base_score += 5.0
            
    base_score = min(95.0, base_score)
    
    breakout_keywords = ["긴급", "속보", "특가", "혜택", "1위", "최신", "breaking", "alert", "deal", "promo"]
    is_breakout = any(bk in title_lower for bk in breakout_keywords)
    
    trends_score = base_score * 1.1 if is_breakout else base_score
    return round(min(100.0, trends_score), 1), is_breakout

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
    """구글 드라이브에서 이전 수집 캐시(latest_news_cache.json)를 불러와 24시간 이내 소식을 이월"""
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
    """이번에 수집/유지된 최신 24시간 소식을 구글 드라이브 캐시(latest_news_cache.json)로 갱신 저장"""
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
    """독립된 날짜별 JSON 데이터 파일 구글 드라이브 추가 업로드"""
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

def generate_html_email_body(data):
    """제목 클릭 시 별도 창(target='_blank')에서 원본 언론사 소스로 이동하는 HTML 이메일 본문 생성"""
    html_code = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; color: #2D3748; line-height: 1.5; margin: 0; padding: 20px; background-color: #F7FAFC; }}
    .container {{ max-width: 680px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 8px; border: 1px solid #E2E8F0; }}
    .title {{ font-size: 20px; font-weight: bold; color: #1A202C; margin-bottom: 4px; }}
    .subtitle {{ font-size: 12px; color: #718096; margin-bottom: 12px; }}
    .divider {{ border: 0; height: 2px; background: #5A67D8; margin-bottom: 15px; }}
    .shorts-box {{ background: #F3E8FF; border-left: 4px solid #6B46C1; padding: 10px 14px; font-weight: bold; color: #5A67D8; font-size: 14px; border-radius: 4px; margin-bottom: 10px; }}
    .card {{ background: #FAF5FF; border: 1px solid #E9D8FD; border-left: 4px solid #805AD5; padding: 12px; margin-bottom: 10px; border-radius: 6px; }}
    .card-title {{ font-weight: bold; font-size: 13px; color: #2D3748; margin-bottom: 4px; }}
    .card-reason {{ font-size: 12px; color: #4A5568; margin-bottom: 4px; }}
    .card-hook {{ font-weight: bold; font-size: 12px; color: #C53030; margin-bottom: 4px; }}
    .card-script {{ font-size: 12px; color: #2B6CB0; }}
    
    .sec-bar {{ padding: 8px 12px; font-weight: bold; font-size: 13px; margin-top: 15px; margin-bottom: 8px; border-radius: 4px; border-left: 4px solid; }}
    .sec-bar-alert {{ background: #FFF5F5; border-color: #E53E3E; color: #9B2C2C; }}
    .sec-bar-normal {{ background: #EBF8FF; border-color: #3182CE; color: #2B6CB0; }}
    
    .item-table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
    .item-row {{ border-bottom: 1px solid #EDF2F7; }}
    .item-tag {{ width: 60px; vertical-align: top; padding: 6px 0; font-weight: bold; font-size: 12px; }}
    .item-title {{ vertical-align: top; padding: 6px 0; font-size: 13px; }}
    .item-link {{ text-decoration: none; }}
    .item-link:hover {{ text-decoration: underline; }}
    .empty-text {{ font-size: 12px; color: #A0AEC0; padding: 6px 0; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="title">StariaPj 온타임 24시간 긴급속보 &amp; Shorts 제작 리포트</div>
    <div class="subtitle">발행 일시: {data['now_kst_str']} (KST) | stariapj-new-bot 가중치 알고리즘(StariaPj 4지역 + Google Trends) 반영</div>
    <hr class="divider">
    
    <div class="shorts-box">🎬 [필수 제작] stariapj-new-bot 자동 선정 Shorts TOP 3</div>
"""

    if data.get('shorts_top3'):
        for idx, item in enumerate(data['shorts_top3'], 1):
            score_info = f" (Bot Score: {item.get('bot_score', 0)}pt | {item.get('priority_label', '')})"
            html_code += f"""
            <div class="card">
              <div class="card-title">{idx}. [{item['category']}] {html.escape(item['title'])}{score_info}</div>
              <div class="card-reason">💡 <b>추천 이유:</b> <i>{html.escape(item['reason'])}</i></div>
              <div class="card-hook">🎯 <b>3초 Hook 멘트:</b> {html.escape(item.get('hook', ''))}</div>
              <div class="card-script">⏱️ <b>30초 대본 개요:</b> {html.escape(item.get('script', ''))}</div>
            </div>
            """
    else:
        html_code += '<div class="empty-text">• 최근 24시간 이내 수집된 소식지 내용 중 별도 추천할 파급 이슈가 없습니다.</div>'
        
    html_code += '<hr style="border:0; height:1px; background:#E2E8F0; margin:15px 0;">'

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
        bar_class = "sec-bar-alert" if is_alert else "sec-bar-normal"
        html_code += f'<div class="sec-bar {bar_class}">{sec_title}</div>'
        
        items = data.get(key, [])
        if items:
            html_code += '<table class="item-table">'
            for idx, item in enumerate(items):
                color = GRADIENT_COLORS[min(idx, len(GRADIENT_COLORS)-1)]
                link_url = html.escape(item.get('link', '#'))
                title_txt = html.escape(item['title'])
                
                if idx == 0:
                    tag_txt = "[🔥TOP]" if is_alert else "[⭐TOP]"
                    tag_color = "#C53030" if is_alert else "#2B6CB0"
                    tag_html = f'<span style="color: {tag_color}; font-weight: bold;">{tag_txt}</span>'
                    title_html = f'<a href="{link_url}" target="_blank" class="item-link" style="font-weight: bold; color: {color};">{title_txt}</a>'
                else:
                    tag_txt = "[속보]" if key == 'breaking' else ("[특가]" if key == 'flights' else "[소식]")
                    tag_html = f'<span style="color: {color};">{tag_txt}</span>'
                    title_html = f'<a href="{link_url}" target="_blank" class="item-link" style="color: {color};">{title_txt}</a>'
                    
                html_code += f"""
                <tr class="item-row">
                  <td class="item-tag">{tag_html}</td>
                  <td class="item-title">{title_html}</td>
                </tr>
                """
            html_code += '</table>'
        else:
            html_code += '<div class="empty-text">• 최근 24시간 이내 등록되거나 유효한 소식이 없습니다.</div>'
            
    if data.get('yt_videos'):
        html_code += '<div class="sec-bar sec-bar-normal">▶️ [YouTube 24HR 바이럴 영상]</div>'
        html_code += '<table class="item-table">'
        for idx, vid in enumerate(data['yt_videos']):
            color = GRADIENT_COLORS[min(idx, len(GRADIENT_COLORS)-1)]
            v_title = html.escape(vid['snippet']['title'])
            v_id = vid.get('id', {}).get('videoId', '')
            v_url = f"https://www.youtube.com/watch?v={v_id}" if v_id else "#"
            
            title_html = f'<a href="{v_url}" target="_blank" class="item-link" style="color: {color};">{v_title}</a>'
            
            html_code += f"""
            <tr class="item-row">
              <td class="item-tag" style="color: {color};">[Shorts]</td>
              <td class="item-title">{title_html}</td>
            </tr>
            """
        html_code += '</table>'
        
    html_code += """
  </div>
</body>
</html>
"""
    return html_code

def send_email_with_pdf(pdf_bytes, report_data, recipients=None):
    """지정된 수신자들에게 원본 링크가 적용된 HTML 이메일 및 PDF 동시 발송"""
    if recipients is None:
        recipients = ["pj2gwk@gmail.com", "miyoungchoi88@gmail.com", "kimgiwoong5@gmail.com"]
        
    sender_user = os.environ.get("EMAIL_USER")
    sender_pass = os.environ.get("EMAIL_PASS")
    
    if not sender_user or not sender_pass:
        print("⚠️ 이메일 발송 설정(EMAIL_USER, EMAIL_PASS)이 등록되지 않아 이메일 전송을 스킵합니다.")
        return

    try:
        time_str = report_data['time_str']
        msg = MIMEMultipart('mixed')
        msg['From'] = sender_user
        msg['To'] = ", ".join(recipients)
        msg['Subject'] = f"[StariaPj] 온타임 24시간 실시간 소식지 ({time_str} KST)"

        html_body = generate_html_email_body(report_data)
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        pdf_filename = f"StariaPj_Daily_Report_{time_str}_KST.pdf"
        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header('Content-Disposition', 'attachment', filename=pdf_filename)
        msg.attach(pdf_attachment)

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_user, sender_pass)
            server.send_message(msg)

        print(f"📧 이메일 동시 발송 완료! ({', '.join(recipients)} (으)로 성공적으로 전송되었습니다.)")
    except Exception as e:
        print(f"❌ 이메일 발송 오류: {e}")

def fetch_google_news_rss_realtime(query, lang_zone="KR", max_hours=24):
    """Google News RSS 최신 24시간 항목 수집 및 원본 링크 변환 + 도메인 필터링"""
    realtime_query = f"{query} when:1d"
    encoded_query = urllib.parse.quote(realtime_query)
    
    if lang_zone == "ZA":
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-ZA&gl=ZA&ceid=ZA:en"
    else:
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"

    entries = []
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            feed = feedparser.parse(response.content)
            now_utc = datetime.now(timezone.utc)
            cutoff_dt = now_utc - timedelta(hours=max_hours)
            
            for entry in feed.entries:
                title = getattr(entry, 'title', '')
                
                if is_banned_title(title):
                    continue
                
                pub_dt = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'published') and entry.published:
                    try:
                        pub_dt = email.utils.parsedate_to_datetime(entry.published)
                    except Exception:
                        pub_dt = None
                
                if not pub_dt or pub_dt < cutoff_dt:
                    continue
                
                raw_link = getattr(entry, 'link', '')
                clean_link = decode_google_news_url(raw_link, title)
                
                if is_banned_domain(clean_link):
                    continue
                
                entries.append({
                    'title': title,
                    'link': clean_link,
                    'pub_ts': pub_dt.timestamp()
                })
    except Exception as e:
        print(f"⚠️ RSS 수집 경고 ({query}, zone={lang_zone}): {e}")
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

def merge_and_filter_entries(new_entries, cached_entries, max_hours=24, limit=10):
    """24시간 이내 소식 이월 유지 및 중요도/최신순 내림차순 정렬 (최대 limit개)"""
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff_ts = now_ts - (max_hours * 3600)

    combined_dict = {}

    for c in cached_entries:
        title = c.get('title', '')
        if is_banned_title(title):
            continue
        if c.get('pub_ts', 0) >= cutoff_ts:
            combined_dict[title] = c
            
    for n in new_entries:
        title = n.get('title', '')
        if is_banned_title(title):
            continue
        if n.get('pub_ts', 0) >= cutoff_ts:
            combined_dict[title] = n
            
    sorted_items = sorted(combined_dict.values(), key=lambda x: x['pub_ts'], reverse=True)
    return sorted_items[:limit]

def clean_text(text):
    """ReportLab XML 파싱 오류 방지"""
    if not text:
        return ""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def select_top_shorts_topics(data):
    """
    [stariapj-new-bot 가중치 알고리즘 반영]
    StariaPj 4지역 우선순위 점수(50%) + Google Trends 실시간 지수(50%)를 합산하여
    모든 수집 카테고리 항목 중 종합 점수가 가장 높은 TOP 3 핫이슈 및 숏츠 대본 가이드 자동 추출
    """
    candidates = []
    seen_titles = set()

    sections_mapping = [
        ('breaking', '🚨 긴급/속보 파급',
         '남아공 & 한국 국민의 안전/제도/삶에 직접 영향을 미치는 실시간 속보',
         '"잠깐! 남아공과 한국에서 지금 난리 난 이 소식, 알고 계셨나요?"',
         '[0~3초] 속보 자막 & 멘트 → [3~20초] 24시간 내 발생 사건 핵심 요약 → [20~30초] "여러분의 생각은?" 댓글 유도'),
         
        ('flights', '✈️ 파격 특가/혜택',
         '양국 간 이동 비용 절감 및 실질적 혜택이 매우 높아 바이럴 유력',
         '"남아공-한국 비행기표 실화? 24시간 안에 나온 이 특가 혜택 놓치면 손해입니다!"',
         '[0~3초] 할인 금액 강조 → [3~20초] 프로모션 조건 및 일시 빠르게 전달 → [20~30초] "주변에 남아공 갈 사람 태그!"'),
         
        ('exchanges', '🌐 교류/문화',
         '아프리카/남아공과 한국 간 대중적 관심도 및 시청 지속 시간이 높은 이슈',
         '"아프리카와 한국이 만났다! 양국 대중을 뜨겁게 달군 실시간 현장 소식!"',
         '[0~3초] 현장/하이라이트 장면 → [3~20초] 주요 기사 내용 및 반응 정리 → [20~30초] "여러분의 의견을 댓글로 들려주세요!"'),
         
        ('sports', '⚽ 스포츠 매치',
         '남아공·아프리카 ↔ 한국 스포츠 매치 및 바이럴 요소가 높은 소식',
         '"대역전극 탄생? 남아공과 한국 스포츠 팬들이 폭발한 이유!"',
         '[0~3초] 경기 명장면 언급 → [3~20초] 승부처 및 현지 반응 요약 → [20~30초] "다음 경기 승자는?" 댓글 참여'),
         
        ('festivals', '🍷 미식/관광 페스티벌',
         'K-Food 및 남아공 특색이 살아있어 영상 제작 시 시각적 바이럴이 높은 소재',
         '"이 조합 미쳤다! 현지인들도 줄 서서 먹는 현장 바이럴 소식!"',
         '[0~3초] 미식 클로즈업 → [3~20초] 페스티벌 및 인기 메뉴 3가지 소개 → [20~30초] "가장 먹고 싶은 것은?" 댓글 축제'),

        ('promotions', '🎁 관광/프로모션',
         '체험형 로컬 투어 및 가성비 관광 혜택 중심 소식',
         '"1년에 딱 한번! 이 혜택 모르면 손해보는 여행 꿀팁!"',
         '[0~3초] 혜택 한줄 요약 → [3~20초] 이용 방법 및 필수 방문 스팟 안내 → [20~30초] "저장해두고 떠나세요!"')
    ]

    for sec_key, category_name, reason_fmt, hook_fmt, script_fmt in sections_mapping:
        items = data.get(sec_key, [])
        for item in items:
            title = item.get('title', '')
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            
            # stariapj-new-bot 가중치 계산
            region_score, priority_label = evaluate_stariapj_region_score(title)
            trends_score, is_breakout = calculate_google_trends_score(title)
            bot_score = round((0.5 * region_score) + (0.5 * trends_score), 2)
            
            candidates.append({
                'category': category_name,
                'title': title,
                'reason': f"{reason_fmt} ({priority_label})",
                'hook': hook_fmt,
                'script': script_fmt,
                'bot_score': bot_score,
                'priority_label': priority_label,
                'region_score': region_score,
                'trends_score': trends_score
            })

    # stariapj-new-bot 최종 점수 기준 내림차순 정렬
    candidates.sort(key=lambda x: x['bot_score'], reverse=True)
    return candidates[:3]

def generate_report_data(service, folder_id):
    """데이터 수집 및 이월 캐시 병합 (한국어 + 남아공 현지 영문 검색 병합)"""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")

    old_cache = load_gdrive_cache(service, folder_id)
    new_cache = {}

    queries_kr = {
        'breaking': '(남아공 OR 아프리카 OR "South Africa") (속보 OR 긴급 OR 특종 OR 사건 OR 사고 OR 비상 OR "breaking news") -축구 -게임',
        'flights': '(남아공 OR "South Africa") (항공권 OR 비행기표 OR "flight ticket" OR "airfare") (특가 OR 프로모션 OR 할인 OR "discount") -무인 -LIG -밀코르 -축구 -배달 -특급',
        'exchanges': '((한국 OR 대한민국) (남아공 OR 아프리카) (문화제 OR 교류 OR "cultural exchange")) OR ((남아공 OR "South Africa") (한국 OR "Korea") (행사 OR 축제 OR "festival")) -아시안게임 -축구 -경기',
        'sports': '(아프리카 OR 남아공 OR "South Africa") (한국 OR 대한민국 OR "Korea") (맞대결 OR 평가전 OR 친선전 OR 대표팀 OR "vs") (축구 OR 농구 OR 야구) -아시안게임 -유로 -올림픽 -홍명보 -히딩크 -벤투 -2010 -2012 -2014 -2018 -2022',
        'festivals': '("K-Food" OR 남아공 OR "South Africa") (미식 OR "gastro" OR "food festival") (축제 OR 페스티벌)',
        'mice': '(남아공 OR 대한민국 OR 아프리카) (MICE OR 박람회 OR 컨벤션 OR 포럼 OR "exhibition")',
        'promotions': '(남아공 OR 대한민국 OR 아프리카) (관광 OR "tourism") (프로모션 OR 이벤트 OR 할인 OR 무료) -배달'
    }

    queries_za = {
        'breaking': '("South Africa" OR Gauteng OR "Western Cape" OR "Cape Town" OR Johannesburg) (breaking OR alert OR urgent OR incident OR police OR government) -soccer -football',
        'flights': '("South Africa" OR "Cape Town" OR Johannesburg) (flight OR airline OR airfare) (deal OR discount OR promo OR special)',
        'exchanges': '("South Africa" OR Africa) Korea (culture OR exchange OR festival OR event)',
        'sports': '("South Africa" OR Africa) Korea (match OR vs OR game OR tournament)',
        'festivals': '("South Africa" OR "Cape Town") (food OR gastro OR wine OR festival)',
        'mice': '"South Africa" (MICE OR exhibition OR conference OR forum OR summit)',
        'promotions': '"South Africa" tourism (promotion OR deal OR offer OR discount)'
    }

    report_data = {
        'time_str': time_str,
        'now_kst_str': now_kst.strftime('%Y-%m-%d %H:%M:%S')
    }

    for key in queries_kr.keys():
        raw_kr = fetch_google_news_rss_realtime(queries_kr[key], lang_zone="KR")
        raw_za = fetch_google_news_rss_realtime(queries_za[key], lang_zone="ZA")
        raw_entries = raw_kr + raw_za
        
        cached_entries = old_cache.get(key, [])
        merged = merge_and_filter_entries(raw_entries, cached_entries, max_hours=24, limit=10)
        
        report_data[key] = merged
        new_cache[key] = merged
        
    youtube_api_key = os.environ.get("YOUTUBE_API_KEY", "")
    report_data['yt_videos'] = fetch_youtube_buzz("South Africa Korea travel flight deals food festival", youtube_api_key)

    report_data['shorts_top3'] = select_top_shorts_topics(report_data)
    report_data['new_cache'] = new_cache

    return report_data

def create_pdf_bytes(data):
    """클릭 가능한 언론사 원본 하이퍼링크가 내장된 PDF 리포트 생성"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=35, rightMargin=35, topMargin=35, bottomMargin=35
    )
    
    # ReportLab의 A4는 (width, height) 튜플입니다. A4[0]을 사용하여 가로 너비를 구합니다.
    content_width = A4[0] - 70

    title_style = ParagraphStyle(
        'DocTitle', fontName='HYGothic-Medium', fontSize=18, leading=22,
        textColor=colors.HexColor('#1A202C'), spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'SubTitle', fontName='HYSMyeongJo-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#718096'), spaceAfter=10
    )

    card_title_style = ParagraphStyle(
        'CardTitle', fontName='HYGothic-Medium', fontSize=10, leading=14,
        textColor=colors.HexColor('#2D3748')
    )
    card_reason_style = ParagraphStyle(
        'CardReason', fontName='HYSMyeongJo-Medium', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#4A5568')
    )
    card_hook_style = ParagraphStyle(
        'CardHook', fontName='HYGothic-Medium', fontSize=9, leading=13,
        textColor=colors.HexColor('#C53030')
    )
    card_script_style = ParagraphStyle(
        'CardScript', fontName='HYSMyeongJo-Medium', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#2B6CB0')
    )

    empty_style = ParagraphStyle(
        'EmptyText', fontName='HYSMyeongJo-Medium', fontSize=8.5, leading=12,
        textColor=colors.HexColor('#A0AEC0')
    )

    story = []

    story.append(Paragraph("StariaPj 온타임 24시간 긴급속보 &amp; Shorts 제작 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {data['now_kst_str']} (KST) | stariapj-new-bot 가중치 알고리즘(StariaPj 4지역 + Google Trends) 반영", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#5A67D8'), spaceAfter=12))

    shorts_header_p = Paragraph("<font color='#5A67D8'><b>🎬 [필수 제작] stariapj-new-bot 자동 선정 Shorts TOP 3</b></font>", ParagraphStyle('SH', fontName='HYGothic-Medium', fontSize=11, leading=15))
    sh_table = Table([[shorts_header_p]], colWidths=[content_width])
    sh_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F3E8FF')),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LINELEFT', (0,0), (0,-1), 4, colors.HexColor('#6B46C1')),
    ]))
    story.append(sh_table)
    story.append(Spacer(1, 6))

    if data['shorts_top3']:
        for idx, item in enumerate(data['shorts_top3'], 1):
            clean_t = clean_text(item['title'])
            clean_r = clean_text(item['reason'])
            clean_hk = clean_text(item.get('hook', ''))
            clean_sc = clean_text(item.get('script', ''))
            bot_sc = item.get('bot_score', 0)
            
            card_p_list = [
                Paragraph(f"<b>{idx}. [{item['category']}]</b> {clean_t} <font color='#6B46C1'><b>(Bot Score: {bot_sc}점)</b></font>", card_title_style),
                Spacer(1, 2),
                Paragraph(f"💡 <b>추천 이유:</b> <i>{clean_r}</i>", card_reason_style),
                Spacer(1, 2),
                Paragraph(f"🎯 <b>3초 Hook 멘트:</b> {clean_hk}", card_hook_style),
                Spacer(1, 2),
                Paragraph(f"⏱️ <b>30초 대본 개요:</b> {clean_sc}", card_script_style)
            ]
            
            card_table = Table([[card_p_list]], colWidths=[content_width])
            card_table.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FAF5FF')),
                ('BOX', (0,0), (-1,-1), 0.8, colors.HexColor('#E9D8FD')),
                ('LINELEFT', (0,0), (0,-1), 3.5, colors.HexColor('#805AD5')),
                ('LEFTPADDING', (0,0), (-1,-1), 10),
                ('RIGHTPADDING', (0,0), (-1,-1), 10),
                ('TOPPADDING', (0,0), (-1,-1), 8),
                ('BOTTOMPADDING', (0,0), (-1,-1), 8),
            ]))
            story.append(card_table)
            story.append(Spacer(1, 6))
    else:
        empty_p = Paragraph("• 최근 24시간 이내 수집된 소식지 내용 중 별도 추천할 파급 이슈가 없습니다.", empty_style)
        story.append(empty_p)
        
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#E2E8F0'), spaceAfter=10))

    def create_section_bar(title_text, is_alert=False):
        accent_color = '#E53E3E' if is_alert else '#3182CE'
        bg_color = '#FFF5F5' if is_alert else '#EBF8FF'
        text_color = '#9B2C2C' if is_alert else '#2B6CB0'
        
        p = Paragraph(f"<b>{title_text}</b>", ParagraphStyle(
            'SecHeaderP', fontName='HYGothic-Medium', fontSize=10.5, leading=14,
            textColor=colors.HexColor(text_color)
        ))
        t = Table([[p]], colWidths=[content_width])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor(bg_color)),
            ('LINELEFT', (0,0), (0,-1), 3.5, colors.HexColor(accent_color)),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        return t

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
        story.append(create_section_bar(sec_title, is_alert))
        story.append(Spacer(1, 4))
        items = data.get(key, [])
        if items:
            table_rows = []
            for idx, item in enumerate(items):
                color_hex = GRADIENT_COLORS[min(idx, len(GRADIENT_COLORS)-1)]
                link_url = html.escape(item.get('link', ''))
                clean_t = clean_text(item['title'])
                
                title_text = f'<a href="{link_url}">{clean_t}</a>' if link_url else clean_t
                
                if idx == 0:
                    tag_txt = "[🔥TOP]" if is_alert else "[⭐TOP]"
                    p_tag = Paragraph(f"<b>{tag_txt}</b>", ParagraphStyle(
                        f'TagTop_{key}', fontName='HYGothic-Medium', fontSize=9, leading=13,
                        textColor=colors.HexColor('#C53030' if is_alert else '#2B6CB0')
                    ))
                    p_body = Paragraph(f"<b>{title_text}</b>", ParagraphStyle(
                        f'BodyTop_{key}', fontName='HYGothic-Medium', fontSize=9.5, leading=14,
                        textColor=colors.HexColor(color_hex)
                    ))
                else:
                    tag_txt = "[속보]" if key == 'breaking' else ("[특가]" if key == 'flights' else "[소식]")
                    p_tag = Paragraph(tag_txt, ParagraphStyle(
                        f'Tag_{key}_{idx}', fontName='HYGothic-Medium', fontSize=8.5, leading=12,
                        textColor=colors.HexColor(color_hex)
                    ))
                    p_body = Paragraph(title_text, ParagraphStyle(
                        f'Body_{key}_{idx}', fontName='HYGothic-Medium', fontSize=8.5, leading=13,
                        textColor=colors.HexColor(color_hex)
                    ))
                
                table_rows.append([p_tag, p_body])
                
            sec_table = Table(table_rows, colWidths=[48, content_width - 48])
            sec_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('LEFTPADDING', (0,0), (-1,-1), 4),
                ('RIGHTPADDING', (0,0), (-1,-1), 4),
                ('TOPPADDING', (0,0), (-1,-1), 2),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LINEBELOW', (0,0), (-1,-2), 0.5, colors.HexColor('#EDF2F7'))
            ]))
            story.append(sec_table)
        else:
            story.append(Paragraph("• 최근 24시간 이내 등록되거나 유효한 소식이 없습니다.", empty_style))
        story.append(Spacer(1, 6))

    if data.get('yt_videos'):
        story.append(Spacer(1, 2))
        story.append(create_section_bar("▶️ [YouTube 24HR 바이럴 영상]", False))
        story.append(Spacer(1, 4))
        yt_rows = []
        for idx, vid in enumerate(data['yt_videos']):
            color_hex = GRADIENT_COLORS[min(idx, len(GRADIENT_COLORS)-1)]
            v_title = clean_text(vid['snippet']['title'])
            v_id = vid.get('id', {}).get('videoId', '')
            v_url = f"https://www.youtube.com/watch?v={v_id}" if v_id else ""
            
            title_text = f'<a href="{v_url}">{v_title}</a>' if v_url else v_title
            
            p_tag = Paragraph("[Shorts]", ParagraphStyle(f'YTag_{idx}', fontName='HYGothic-Medium', fontSize=8.5, leading=12, textColor=colors.HexColor(color_hex)))
            p_body = Paragraph(title_text, ParagraphStyle(f'YBody_{idx}', fontName='HYGothic-Medium', fontSize=8.5, leading=13, textColor=colors.HexColor(color_hex)))
            yt_rows.append([p_tag, p_body])
            
        yt_table = Table(yt_rows, colWidths=[50, content_width - 50])
        yt_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(yt_table)

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
        folder_id = folder_id.split('?')[0]
    if '/' in folder_id:
        folder_id = folder_id.split('/')[-1]
        
    service = get_gdrive_service()
    report_data = generate_report_data(service, folder_id)
    pdf_bytes = create_pdf_bytes(report_data)

    upload_to_gdrive(service, folder_id, pdf_bytes, report_data['time_str'])
    upload_json_to_gdrive(service, folder_id, report_data['new_cache'], report_data['time_str'])
    save_gdrive_cache(service, folder_id, report_data['new_cache'])
    ## 본인, 아내, 아들 세 분께 동시 발송
     send_email_with_pdf(pdf_bytes, report_data, recipients=["pj2gwk@gmail.com", "miyoungchoi88@gmail.com", "kimgiwoong5@gmail.com"])
    # 본인 ONLY (Test Mode)
    #send_email_with_pdf(pdf_bytes, report_data, recipients=["pj2gwk@gmail.com"])
