import io
import os
import sys
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

# 1. 한국어 폰트 등록 (ReportLab 내장 한글 폰트)
pdfmetrics.registerFont(UnicodeCIDFont('HYGothic-Medium'))
pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))

def generate_report_content():
    """
    일일 뉴스/보고서 본문 생성 (기존 뉴스 수집 로직 적용 가능)
    """
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    time_str = now_kst.strftime("%Y-%m-%d_%H%M")
    
    content = f"- StariaPj Daily News Automation 스크립트가 성공적으로 실행되었습니다.\n"
    content += f"- GitHub Actions를 통해 PDF 보고서 형태로 Google Drive에 자동 업로드되었습니다.\n"
    content += f"- 생성 시간: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} (KST)\n"
    
    return content, time_str

def create_pdf_bytes(content_text, time_str):
    """
    보고서 텍스트를 깔끔한 PDF 문서(바이너리)로 생성
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
        'DocTitle',
        fontName='HYGothic-Medium',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#1A365D'),
        spaceAfter=8
    )
    
    subtitle_style = ParagraphStyle(
        'SubTitle',
        fontName='HYSMyeongJo-Medium',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4A5568'),
        spaceAfter=15
    )
    
    h2_style = ParagraphStyle(
        'Heading2',
        fontName='HYGothic-Medium',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#2B6CB0'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'BodyCustom',
        fontName='HYSMyeongJo-Medium',
        fontSize=10,
        leading=15,
        textColor=colors.HexColor('#2D3748'),
        spaceAfter=8
    )

    story = []
    
    # 보고서 타이틀 및 날짜 헤더
    formatted_date = f"{time_str[:10]} {time_str[11:13]}:{time_str[13:]}"
    story.append(Paragraph("StariaPj 일일 뉴스 리포트", title_style))
    story.append(Paragraph(f"발행 일시: {formatted_date} (KST)", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#3182CE'), spaceAfter=15))
    
    # 본문 구성
    story.append(Paragraph("■ 자동화 요약 (Summary)", h2_style))
    
    for line in content_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#'):
            line = line.lstrip('#').strip()
            story.append(Paragraph(line, h2_style))
        elif line.startswith('-'):
            line = line.lstrip('-').strip()
            story.append(Paragraph(f"• {line}", body_style))
        else:
            story.append(Paragraph(line, body_style))
            
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
    content_text, time_str = generate_report_content()
    pdf_bytes = create_pdf_bytes(content_text, time_str)
    upload_to_gdrive(pdf_bytes, time_str)
