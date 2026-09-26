import io
import random
import tempfile
import zipfile
from pathlib import Path
import streamlit as st
import fitz  # PyMuPDF
from PIL import Image
import genanki

# ----------------- 페이지 기본 설정 -----------------
st.set_page_config(
    page_title="PicExtract - Image Extractor & Anki Deck Builder",
    page_icon="🧬",
    layout="centered"
)

# ----------------- 모던 클리니컬 UI 스타일링 (CSS) -----------------
st.markdown("""
<style>
    .stApp {
        background-color: #F1F5F9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .block-container {
        max-width: 740px !important;
        padding-top: 2rem !important;
        padding-bottom: 4rem !important;
    }
    .main-card {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 30px 24px 24px 24px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.04);
        border: 1px solid #E2E8F0;
        margin-bottom: 24px;
    }
    .badge {
        display: inline-block;
        padding: 4px 12px;
        background-color: #EFF6FF;
        color: #2563EB;
        font-size: 12px;
        font-weight: 600;
        border-radius: 20px;
        margin-bottom: 12px;
    }
    .main-title {
        font-size: 28px;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.6px;
        margin-bottom: 8px;
    }
    .main-subtitle {
        font-size: 14px;
        color: #64748B;
        line-height: 1.6;
    }
    div[data-testid="stFileUploader"] {
        background-color: #FFFFFF;
        border: 2px dashed #93C5FD !important;
        border-radius: 16px !important;
        padding: 28px 24px !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.03);
    }
    div[data-testid="stFileUploader"]:hover {
        border-color: #2563EB !important;
        background-color: #F8FAFC;
    }
    .stButton > button {
        width: 100%;
        background-color: #2563EB !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        height: 48px !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        box-shadow: 0 4px 10px rgba(37, 99, 235, 0.25) !important;
        margin-top: 10px;
    }
    .stButton > button:hover {
        background-color: #1D4ED8 !important;
    }
    .anki-btn button {
        background-color: #4F46E5 !important; /* Anki 인디고 블루 */
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        height: 48px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 10px rgba(79, 70, 229, 0.25) !important;
    }
    .zip-btn button {
        background-color: #059669 !important; /* 에메랄드 그린 */
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        height: 48px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 10px rgba(5, 150, 105, 0.25) !important;
    }
    .feature-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 14px;
        margin-top: 28px;
    }
    .feature-item {
        background: #FFFFFF;
        padding: 16px 12px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        text-align: center;
    }
    .feature-title {
        font-size: 13px;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 4px;
    }
    .feature-desc {
        font-size: 11px;
        color: #64748B;
        line-height: 1.4;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 헤더 -----------------
st.markdown("""
<div class="main-card">
    <span class="badge">STUDY ACCELERATOR</span>
    <div class="main-title">PicExtract</div>
    <div class="main-subtitle">
        강의 슬라이드에서 <b>배경과 필기를 제외한 핵심 의학 도표</b>만 추출하여<br>
        즉시 학습 가능한 <b>Anki 덱(.apkg)</b> 및 압축 파일로 변환합니다.
    </div>
</div>
""", unsafe_allow_html=True)


# ----------------- 필터링 엔진 -----------------
def is_meaningful_image(image_bytes: bytes) -> bool:
    if len(image_bytes) < 5120:
        return False
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            w, h = img.size
            if w < 150 or h < 150:
                return False

            thumb = img.convert("RGBA").resize((150, 150), Image.Resampling.BOX)
            pixels = list(thumb.getdata())
            total_pixels = len(pixels)

            # 중앙 영역 공백 검사 (배경 템플릿 테두리 제거)
            center_blank = sum(
                1 for y in range(25, 125) for x in range(25, 125)
                if pixels[y * 150 + x][3] <= 20
                or (pixels[y * 150 + x][0] >= 240 and pixels[y * 150 + x][1] >= 240 and pixels[y * 150 + x][2] >= 240)
                or (pixels[y * 150 + x][0] <= 15 and pixels[y * 150 + x][1] <= 15 and pixels[y * 150 + x][2] <= 15)
            )
            if (center_blank / 10000) > 0.95:
                return False

            # 필기 패턴 검사
            non_bg_count = 0
            visible_count = 0
            non_bg_colors = []
            for r, g, b, a in pixels:
                if a > 20:
                    visible_count += 1
                    if not ((r <= 15 and g <= 15 and b <= 15) or (r >= 240 and g >= 240 and b >= 240)):
                        non_bg_count += 1
                        non_bg_colors.append((r // 32, g // 32, b // 32))

            if (visible_count / total_pixels) < 0.06 or (non_bg_count / total_pixels) < 0.06:
                return False

            if non_bg_colors:
                if len(set(non_bg_colors)) < 12 and (non_bg_count / total_pixels) < 0.20:
                    return False

            if (total_pixels - non_bg_count) / total_pixels > 0.75:
                return False
    except Exception:
        return False
    return True


# ----------------- Anki 덱 빌더 함수 -----------------
def generate_anki_package(image_records: list, deck_title: str) -> bytes:
    """
    image_records: [(filename, image_bytes, page_info_text), ...]
    Anki 덱과 미디어 파일을 패키징하여 .apkg 바이트 데이터를 반환합니다.
    """
    model_id = random.randrange(1 << 30, 1 << 31)
    deck_id = random.randrange(1 << 30, 1 << 31)

    # 심플하고 가독성 좋은 Anki 카드 모델 정의
    my_model = genanki.Model(
        model_id,
        "PicExtract Medical Card",
        fields=[
            {"name": "Image"},
            {"name": "SourceInfo"},
            {"name": "Notes"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": """
                    <div style="font-family: Arial; text-align: center; color: #475569; font-size: 13px; margin-bottom: 8px;">
                        {{SourceInfo}}
                    </div>
                    <div style="text-align: center;">
                        {{Image}}
                    </div>
                """,
                "afmt": """
                    {{FrontSide}}
                    <hr id="answer" style="border: 0; border-top: 1px solid #CBD5E1; margin: 16px 0;">
                    <div style="font-family: Arial; text-align: center; color: #0F172A; font-size: 16px; font-weight: bold;">
                        {{Notes}}
                    </div>
                """,
            },
        ],
        css="""
            .card {
                background-color: #FFFFFF;
                border-radius: 8px;
                padding: 14px;
            }
            img {
                max-width: 95%;
                max-height: 520px;
                height: auto;
                border-radius: 6px;
                box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            }
        """
    )

    my_deck = genanki.Deck(deck_id, f"PicExtract::{deck_title}")
    media_files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for fname, img_bytes, src_info in image_records:
            # Anki 미디어 디렉토리용 임시 파일 저장
            temp_path = Path(tmpdir) / fname
            with open(temp_path, "wb") as f:
                f.write(img_bytes)
            media_files.append(str(temp_path))

            # 카드 추가 (앞면: 그림, 뒷면: 슬라이드 출처/메모)
            note = genanki.Note(
                model=my_model,
                fields=[
                    f'<img src="{fname}">',
                    f"📑 {src_info}",
                    "확인 완료"
                ]
            )
            my_deck.add_note(note)

        pkg = genanki.Package(my_deck)
        pkg.media_files = media_files

        output_apkg_path = Path(tmpdir) / "output.apkg"
        pkg.write_to_file(str(output_apkg_path))

        with open(output_apkg_path, "rb") as f:
            apkg_bytes = f.read()

    return apkg_bytes


# ----------------- 파일 업로드 및 추출 파이프라인 -----------------
uploaded_files = st.file_uploader(
    "문서 파일을 드래그하여 올려놓으세요",
    type=["pdf", "pptx"],
    accept_multiple_files=True,
    label_visibility="collapsed"
)

if uploaded_files:
    if st.button(f"▶ {len(uploaded_files)}개 문서 처리 시작", type="primary"):
        with st.spinner("이미지 정밀 필터링 및 Anki 덱 생성 중..."):
            zip_buffer = io.BytesIO()
            image_records = []
            total_saved = 0
            total_skipped = 0

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_out:
                for uploaded_file in uploaded_files:
                    base_name = Path(uploaded_file.name).stem
                    suffix = Path(uploaded_file.name).suffix.lower()
                    file_bytes = uploaded_file.read()

                    if suffix == ".pdf":
                        doc = fitz.open(stream=file_bytes, filetype="pdf")
                        for p_idx, page in enumerate(doc):
                            for img_idx, img in enumerate(page.get_images(full=True)):
                                img_data = doc.extract_image(img[0])
                                b = img_data["image"]
                                ext = img_data["ext"]
                                if is_meaningful_image(b):
                                    fname = f"{base_name}_p{p_idx+1}_{img_idx+1}.{ext}"
                                    zip_out.writestr(fname, b)
                                    image_records.append((fname, b, f"{base_name} (Page {p_idx+1})"))
                                    total_saved += 1
                                else:
                                    total_skipped += 1
                        doc.close()

                    elif suffix == ".pptx":
                        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
                            counter = 1
                            for item in z.infolist():
                                if item.filename.startswith("ppt/media/"):
                                    b = z.read(item)
                                    if is_meaningful_image(b):
                                        ext = Path(item.filename).suffix
                                        fname = f"{base_name}_img{counter}{ext}"
                                        zip_out.writestr(fname, b)
                                        image_records.append((fname, b, f"{base_name} (Image {counter})"))
                                        counter += 1
                                        total_saved += 1
                                    else:
                                        total_skipped += 1

            if total_saved > 0:
                st.success(f"✔ 처리 완료: 총 {total_saved}장의 유효 도표를 확보했습니다. ({total_skipped}개 배경/필기 자동 제외)")
                
                # Anki 덱 생성
                first_doc_title = Path(uploaded_files[0].name).stem
                apkg_data = generate_anki_package(image_records, first_doc_title)

                # 다운로드 버튼 영역 (2단 분할)
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown('<div class="anki-btn">', unsafe_allow_html=True)
                    st.download_button(
                        label="⚡ Anki 덱(.apkg) 다운로드",
                        data=apkg_data,
                        file_name=f"{first_doc_title}_Deck.apkg",
                        mime="application/octet-stream"
                    )
                    st.markdown('</div>', unsafe_allow_html=True)

                with col2:
                    st.markdown('<div class="zip-btn">', unsafe_allow_html=True)
                    st.download_button(
                        label="📦 이미지 ZIP 다운로드",
                        data=zip_buffer.getvalue(),
                        file_name=f"{first_doc_title}_images.zip",
                        mime="application/zip"
                    )
                    st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.warning("유효한 본문 이미지가 감지되지 않았거나 모든 이미지가 템플릿/필기로 판별되었습니다.")

# ----------------- 하단 기능 소개 카드 -----------------
st.markdown("""
<div class="feature-grid">
    <div class="feature-item">
        <div class="feature-title">🛡️ 노이즈 필터</div>
        <div class="feature-desc">배경 슬라이드 틀과 손필기를 배제하고 순수 다이어그램만 선별</div>
    </div>
    <div class="feature-item">
        <div class="feature-title">⚡ Anki 즉시 임포트</div>
        <div class="feature-desc">출처 페이지 정보가 매핑된 카드 덱(.apkg) 더블 클릭으로 추가</div>
    </div>
    <div class="feature-item">
        <div class="feature-title">🏷️ 이미지 오클루전 대비</div>
        <div class="feature-desc">Anki의 'Image Occlusion' 기능으로 빈칸 가림 복습에 최적화</div>
    </div>
</div>
""", unsafe_allow_html=True)