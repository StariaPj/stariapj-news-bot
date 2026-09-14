import os
import sys
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

def generate_report():
    """
    일일 뉴스/마크다운 리포트를 생성하는 함수
    (필요에 따라 기존 뉴스 수집 logic 코드로 교체 가능합니다)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    content = f"# StariaPj Daily Report ({today_str})\n\n"
    content += "## Today's Automation Summary\n"
    content += "- StariaPj Daily News Automation script ran successfully.\n"
    content += "- Generated via GitHub Actions and uploaded using Google Drive OAuth 2.0.\n"
    return content, today_str

def upload_to_gdrive(content, today_str):
    client_id = os.environ.get("GDRIVE_CLIENT_ID")
    client_secret = os.environ.get("GDRIVE_CLIENT_SECRET")
    refresh_token = os.environ.get("GDRIVE_REFRESH_TOKEN")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")

    # 1. 필수 환경 변수 검증
    if not all([client_id, client_secret, refresh_token, folder_id]):
        print("❌ 오류: Google Drive Secrets (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, FOLDER_ID) 중 일부가 누락되었습니다.")
        sys.exit(1)

    # 2. Folder ID 자동 정제 (URL 전체나 쿼리 스트링, 공백 입력 시 pure ID만 파싱)
    folder_id = folder_id.strip().rstrip('/')
    if '?' in folder_id:
        folder_id = folder_id.split('?')[0]
    if '/' in folder_id:
        folder_id = folder_id.split('/')[-1]

    print(f"📁 Target Folder ID: {folder_id}")

    # 3. OAuth 2.0 Credentials 객체 생성
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/drive.file"]
    )

    try:
        # 4. Google Drive API 서비스 빌드 및 업로드
        service = build("drive", "v3", credentials=creds)

        filename = f"StariaPj_Daily_Report_{today_str}.md"
        file_metadata = {
            "name": filename,
            "parents": [folder_id],
            "mimeType": "text/markdown"
        }

        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown", resumable=True)

        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        print(f"✅ Google Drive 업로드 성공! (파일 ID: {file.get('id')})")

    except Exception as e:
        print(f"❌ Google Drive 업로드 실패: {e}")
        sys.exit(1)

if __name__ == "__main__":
    report_content, today_str = generate_report()
    upload_to_gdrive(report_content, today_str)
