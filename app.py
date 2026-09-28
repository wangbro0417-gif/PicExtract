import io
import random
import tempfile
import zipfile
import hashlib  # 중복 이미지 해시 비교를 위해 추가
from pathlib import Path
import streamlit as st
import fitz  # PyMuPDF
from PIL import Image
import genanki

# ----------------- 페이지 기본 설정 -----------------
st.set_page_config(
    page_title="PicExtract - Image Extractor & Anki Deck Builder",
    page_icon="🧬",
    layout="wide"
)

# ----------------- 모던 클리니컬 UI 스타일링 (CSS) -----------------
st.markdown("""
<style>
    .stApp {
        background-color: #F1F5F9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .block-container {
        max-width: 1100px !important;
        padding-top: 2rem !important;
        padding-bottom: 4rem !important;
    }
    .main-card {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 26px 20px 20px 20px;
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
        margin-bottom: 10px;
    }
    .main-title {
        font-size: 26px;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.5px;
        margin-bottom: 6px;
    }
    .main-subtitle {
        font-size: 13.5px;
        color: #64748B;
        line-height: 1.5;
    }
    div[data-testid="stFileUploader"] {
        background-color: #FFFFFF;
        border: 2px dashed #93C5FD !important;
        border-radius: 16px !important;
        padding: 24px 20px !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.03);
    }
    .gallery-caption {
        font-size: 11px;
        color: #64748B;
        margin-top: 2px;
        word-break: break-all;
        line-height: 1.2;
    }
    .anki-btn button {
        background-color: #4F46E5 !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        height: 48px !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 10px rgba(79, 70, 229, 0.25) !important;
    }
    .zip-btn button {
        background-color: #059669 !important;
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
        margin-top: 36px;
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

# ----------------- 상단 비주얼 헤더 -----------------
st.markdown("""
<div class="main-card">
    <span class="badge">STUDY ACCELERATOR</span>
    <div class="main-title">PicExtract</div>
    <div class="main-subtitle">
        강의 슬라이드에서 핵심 도표를 추출하고, <b>중복 이미지와 표를 자동 배제</b>하여<br>
        필요한 자료만 <b>Anki 덱(.apkg)</b> 및 압축 파일로 일괄 저장하세요.
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

            aspect_ratio = w / h
            if aspect_ratio > 2.5 or aspect_ratio < 0.4:
                return False

            thumb = img.convert("RGBA").resize((150, 150), Image.Resampling.BOX)
            pixels = list(thumb.getdata())
            total_pixels = len(pixels)

            center_blank = sum(
                1 for y in range(25, 125) for x in range(25, 125)
                if pixels[y * 150 + x][3] <= 20
                or (pixels[y * 150 + x][0] >= 240 and pixels[y * 150 + x][1] >= 240 and pixels[y * 150 + x][2] >= 240)
                or (pixels[y * 150 + x][0] <= 15 and pixels[y * 150 + x][1] <= 15 and pixels[y * 150 + x][2] <= 15)
            )
            if (center_blank / 10000) > 0.95:
                return False

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


# ----------------- Anki 패키지 빌더 -----------------
def generate_anki_package(selected_records: list) -> bytes:
    model_id = random.randrange(1 << 30, 1 << 31)
    my_model = genanki.Model(
        model_id,
        "PicExtract Medical Card",
        fields=[
            {"name": "Image"},
            {"name": "SourceInfo"},
            {"name": "CaptionText"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": """
                    <div style="font-family: -apple-system, sans-serif; text-align: center; color: #64748B; font-size: 13px; margin-bottom: 8px;">
                        {{SourceInfo}}
                    </div>
                    <div style="text-align: center;">
                        {{Image}}
                    </div>
                """,
                "afmt": """
                    {{FrontSide}}
                    <hr id="answer" style="border: 0; border-top: 1px solid #CBD5E1; margin: 16px 0;">
                    <div style="font-family: -apple-system, sans-serif; text-align: left; color: #0F172A; font-size: 13px; line-height: 1.4; background: #F8FAFC; padding: 10px; border-radius: 6px;">
                        <b>Context:</b><br>{{CaptionText}}
                    </div>
                """,
            },
        ],
        css="""
            .card { background-color: #FFFFFF; border-radius: 8px; padding: 16px; }
            img { max-width: 95%; max-height: 540px; height: auto; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        """
    )

    decks = {}
    media_files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for item in selected_records:
            fname = item["fname"]
            img_bytes = item["bytes"]
            src_info = item["src_info"]
            doc_name = item["doc_name"]
            caption = item.get("caption", "추출된 텍스트 없음")

            clean_deck_name = doc_name.replace("::", "_").strip()
            if clean_deck_name not in decks:
                deck_id = random.randrange(1 << 30, 1 << 31)
                decks[clean_deck_name] = genanki.Deck(deck_id, clean_deck_name)

            temp_path = Path(tmpdir) / fname
            with open(temp_path, "wb") as f:
                f.write(img_bytes)
            media_files.append(str(temp_path))

            note = genanki.Note(
                model=my_model,
                fields=[
                    f'<img src="{fname}">',
                    f"📑 {src_info}",
                    caption.replace("\n", "<br>")
                ]
            )
            decks[clean_deck_name].add_note(note)

        pkg = genanki.Package(list(decks.values()))
        pkg.media_files = media_files

        output_apkg_path = Path(tmpdir) / "output.apkg"
        pkg.write_to_file(str(output_apkg_path))

        with open(output_apkg_path, "rb") as f:
            apkg_bytes = f.read()

    return apkg_bytes


# ----------------- 세션 상태 초기화 -----------------
if "extracted_items" not in st.session_state:
    st.session_state.extracted_items = []
if "batch_name" not in st.session_state:
    st.session_state.batch_name = "PicExtract"

# ----------------- 파일 업로더 -----------------
uploaded_files = st.file_uploader(
    "문서 파일을 드래그하여 올려놓으세요",
    type=["pdf", "pptx"],
    accept_multiple_files=True,
    label_visibility="collapsed"
)

if uploaded_files:
    if st.button(f"▶ {len(uploaded_files)}개 문서 도표 1차 추출", type="primary"):
        with st.spinner("배경, 표, 중복 이미지를 걸러내며 도표를 추출하는 중입니다..."):
            extracted = []
            skipped = 0
            duplicate_count = 0
            seen_image_hashes = set()  # 중복 제거를 위한 해시 집합

            for uploaded_file in uploaded_files:
                base_name = Path(uploaded_file.name).stem
                suffix = Path(uploaded_file.name).suffix.lower()
                file_bytes = uploaded_file.read()

                if suffix == ".pdf":
                    doc = fitz.open(stream=file_bytes, filetype="pdf")
                    for p_idx, page in enumerate(doc):
                        page_text = page.get_text()

                        for img_idx, img in enumerate(page.get_images(full=True)):
                            img_data = doc.extract_image(img[0])
                            b = img_data["image"]
                            ext = img_data["ext"]

                            if is_meaningful_image(b):
                                # 이미지 바이너리의 MD5 해시값 계산 (완벽한 중복 판별용)
                                img_hash = hashlib.md5(b).hexdigest()
                                if img_hash in seen_image_hashes:
                                    duplicate_count += 1
                                    continue  # 이미 추출된 동일한 사진이면 배제
                                
                                seen_image_hashes.add(img_hash)

                                fname = f"{base_name}_p{p_idx+1}_{img_idx+1}.{ext}"
                                
                                medical_keywords = ['artery', 'nerve', 'vein', 'muscle', 'foramen', 'nucleus', 'glossa', 'heart', 'brain', 'bone', 'arteria', 'nervus']
                                has_keyword = any(kw in page_text.lower() for kw in medical_keywords)

                                extracted.append({
                                    "id": f"{base_name}_{p_idx}_{img_idx}",
                                    "fname": fname,
                                    "bytes": b,
                                    "src_info": f"{base_name} (p.{p_idx+1})",
                                    "doc_name": base_name,
                                    "caption": page_text.strip()[:300],
                                    "selected": has_keyword
                                })
                            else:
                                skipped += 1
                    doc.close()

                elif suffix == ".pptx":
                    with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as z:
                        counter = 1
                        for item in z.infolist():
                            if item.filename.startswith("ppt/media/"):
                                b = z.read(item)
                                if is_meaningful_image(b):
                                    img_hash = hashlib.md5(b).hexdigest()
                                    if img_hash in seen_image_hashes:
                                        duplicate_count += 1
                                        continue
                                    
                                    seen_image_hashes.add(img_hash)

                                    ext = Path(item.filename).suffix
                                    fname = f"{base_name}_img{counter}{ext}"
                                    extracted.append({
                                        "id": f"{base_name}_slide_{counter}",
                                        "fname": fname,
                                        "bytes": b,
                                        "src_info": f"{base_name} (#{counter})",
                                        "doc_name": base_name,
                                        "caption": "PPT 슬라이드 이미지",
                                        "selected": True
                                    })
                                    counter += 1
                                else:
                                    skipped += 1

            first_title = Path(uploaded_files[0].name).stem
            st.session_state.batch_name = first_title if len(uploaded_files) == 1 else f"{first_title}_외_{len(uploaded_files)-1}건"
            st.session_state.extracted_items = extracted

            if extracted:
                st.success(f"총 {len(extracted)}개의 도표를 찾았습니다. (표/배경 {skipped}개, 중복 이미지 {duplicate_count}장 자동 배제 완료)")
            else:
                st.warning("유효한 본문 이미지가 감지되지 않았습니다.")


# ----------------- 추출 결과 갤러리 및 선택 UI -----------------
if st.session_state.extracted_items:
    st.write("---")
    
    tool_col1, tool_col2, tool_col3 = st.columns([3, 1, 1])
    with tool_col1:
        st.subheader(f"🖼️ 도표 선별 갤러리 ({len(st.session_state.extracted_items)}장)")
    with tool_col2:
        if st.button("전체 선택", use_container_width=True):
            for item in st.session_state.extracted_items:
                item["selected"] = True
                st.session_state[f"chk_{item['id']}"] = True
            st.rerun()
    with tool_col3:
        if st.button("전체 해제", use_container_width=True):
            for item in st.session_state.extracted_items:
                item["selected"] = False
                st.session_state[f"chk_{item['id']}"] = False
            st.rerun()

    st.caption("저장하지 않을 도표는 체크를 풀어주세요. 체크된 도표만 덱과 압축 파일로 패키징됩니다.")

    cols = st.columns(4)
    for idx, item in enumerate(st.session_state.extracted_items):
        with cols[idx % 4]:
            st.image(item["bytes"], use_container_width=True)
            item["selected"] = st.checkbox(
                f"선택 #{idx+1}",
                value=item.get("selected", True),
                key=f"chk_{item['id']}"
            )
            st.markdown(f"<div class='gallery-caption'>{item['src_info']}</div>", unsafe_allow_html=True)
            st.write("")

    selected_records = [item for item in st.session_state.extracted_items if item["selected"]]

    st.write("---")
    st.markdown(f"**현재 선택된 도표: {len(selected_records)} / {len(st.session_state.extracted_items)}장**")

    if selected_records:
        final_zip_buffer = io.BytesIO()
        with zipfile.ZipFile(final_zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_out:
            for item in selected_records:
                zip_out.writestr(item["fname"], item["bytes"])

        final_apkg_data = generate_anki_package(selected_records)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown('<div class="anki-btn">', unsafe_allow_html=True)
            st.download_button(
                label=f"⚡ 선택된 Anki 덱 다운로드 ({len(selected_records)}장)",
                data=final_apkg_data,
                file_name=f"{st.session_state.batch_name}.apkg",
                mime="application/octet-stream"
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with col2:
            st.markdown('<div class="zip-btn">', unsafe_allow_html=True)
            st.download_button(
                label=f"📦 선택된 이미지 ZIP 다운로드 ({len(selected_records)}장)",
                data=final_zip_buffer.getvalue(),
                file_name=f"{st.session_state.batch_name}_images.zip",
                mime="application/zip"
            )
            st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.warning("선택된 이미지가 없습니다. 다운로드할 이미지를 1장 이상 선택해 주세요.")

# ----------------- 하단 기능 카드 -----------------
st.markdown("""
<div class="feature-grid">
    <div class="feature-item">
        <div class="feature-title">👁️ 4열 와이드 뷰</div>
        <div class="feature-desc">100장 이상의 대량 슬라이드도 스크롤 부담 없이 빠르게 한눈에 검토</div>
    </div>
    <div class="feature-item">
        <div class="feature-title">⚡ 맞춤형 Anki 패키징</div>
        <div class="feature-desc">선택한 카드만 골라 담아 복습 덱을 군더더기 없이 슬림하게 유지</div>
    </div>
    <div class="feature-item">
        <div class="feature-title">🛡️ 원본 해상도 유지</div>
        <div class="feature-desc">압축 손실 없이 슬라이드 원본 그대로 깨끗한 다이어그램 확보</div>
    </div>
</div>
""", unsafe_allow_html=True)
