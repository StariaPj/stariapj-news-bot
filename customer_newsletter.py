"""Language-specific customer newsletters: headlines and original source links."""
import html
import io
import re
import requests
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pathlib import Path
import tempfile
import reportlab
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle

SECTIONS = [
 ("breaking", "Travel alerts & general news", "여행 참고 및 주요 소식"),
 ("flights", "Flights & airline offers", "항공 및 항공권 혜택"),
 ("exchanges", "Culture & exchanges", "문화 및 교류"),
 ("sports", "Sports events", "스포츠 행사"),
 ("festivals", "Food & festivals", "미식 및 축제"),
 ("mice", "Events & exhibitions", "행사 및 박람회"),
 ("promotions", "Tourism offers", "관광 혜택")
]

def translate_headline(text, language):
    text = re.sub(r"^\s*\[(?:ZA|KR|NO)\]\s*", "", text).strip()
    if language == "ko" and re.search(r"[가-힣]", text):
        return text
    if language == "en" and not re.search(r"[가-힣]", text):
        return text
    result = ""
    try:
        response = requests.get("https://translate.googleapis.com/translate_a/single",
            params={"client":"gtx","sl":"auto","tl":language,"dt":"t","q":text},timeout=12)
        response.raise_for_status()
        result = "".join(x[0] for x in response.json()[0] if x[0]).strip()
    except (requests.RequestException, ValueError, KeyError, TypeError):
        pair = "ko|en" if language == "en" else "en|ko"
        response = requests.get("https://api.mymemory.translated.net/get",
            params={"q":text,"langpair":pair},timeout=12)
        response.raise_for_status()
        result = response.json().get("responseData",{}).get("translatedText","").strip()
    if not result or (language=="en" and re.search(r"[가-힣]",result)):
        raise ValueError("Headline translation did not produce the requested language")
    if language=="ko" and not re.search(r"[가-힣]",result):
        raise ValueError("Korean headline translation unavailable")
    return result

def create_customer_pdf(data, language, translator=translate_headline):
    if language == "ko":
        font_path = Path(tempfile.gettempdir())/"StariaPj-NanumGothic-Regular.ttf"
        if not font_path.exists():
            response = requests.get("https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf",timeout=30)
            response.raise_for_status()
            if response.content[:4] != bytes([0,1,0,0]):
                raise ValueError("Invalid Korean font")
            font_path.write_bytes(response.content)
        font = "StariaPjKorean"
    else:
        font_path = Path(reportlab.__file__).parent/"fonts"/"Vera.ttf"
        font = "StariaPjEnglish"
    pdfmetrics.registerFont(TTFont(font,str(font_path)))
    title = "StariaPj 관광 소식지" if language=="ko" else "StariaPj Travel Newsletter"
    buffer=io.BytesIO()
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=38,rightMargin=38,topMargin=38,bottomMargin=38)
    heading=ParagraphStyle("Title",fontName=font,fontSize=19,leading=26,textColor=colors.HexColor("#0d2637"))
    section=ParagraphStyle("Section",fontName=font,fontSize=13,leading=19,spaceBefore=15,spaceAfter=8,textColor=colors.HexColor("#1b4c60"))
    body=ParagraphStyle("Headline",fontName=font,fontSize=10.5,leading=16,spaceAfter=10,textColor=colors.HexColor("#0d2637"))
    meta=ParagraphStyle("Meta",fontName=font,fontSize=9,leading=14,textColor=colors.HexColor("#4b5d64"))
    story=[Paragraph(title,heading),Spacer(1,8),Paragraph(
        ("발행: " if language=="ko" else "Published: ")+html.escape(data["now_kst_str"])+" (KST)",meta),
        Spacer(1,12),HRFlowable(width="100%",thickness=1,color=colors.HexColor("#1b4c60"))]
    for key,en,ko in SECTIONS:
        story.append(Paragraph(ko if language=="ko" else en,section))
        entries=data.get(key,[])
        if not entries:
            story.append(Paragraph("새 소식이 없습니다." if language=="ko" else "No new headlines.",body))
        for index,item in enumerate(entries,1):
            original=item.get("display_title",item.get("title","")) if language=="ko" else item.get("title","")
            text=translator(original,language)
            url=item.get("link","")
            escaped=html.escape(text)
            linked=f'<a href="{html.escape(url,quote=True)}">{escaped}</a>' if url.startswith(("https://","http://")) else escaped
            story.append(Paragraph(f"{index}. {linked}",body))
    if data.get("yt_videos"):
        story.append(Paragraph("여행 관련 영상" if language=="ko" else "Travel videos",section))
        for item in data["yt_videos"]:
            text=translator(item["snippet"]["title"],language)
            vid=item.get("id",{}).get("videoId","")
            url="https://www.youtube.com/watch?v="+vid
            story.append(Paragraph(f'<a href="{html.escape(url,quote=True)}">{html.escape(text)}</a>',body))
    doc.build(story)
    return buffer.getvalue()
