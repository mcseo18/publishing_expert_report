"""네이버 블로그(SmartEditor ONE) 바로 게재용 HTML 변환기 및 소단원별 20개 해시태그 생성기.

기능:
1. 각 단원의 소단원(##)마다 주제·본문 핵심어에 맞춘 중복 없는 정확히 20개의 네이버 블로그용 해시태그 텍스트 생성
   (예: #토양유기물 #토양유기탄소 #POM #MAOM ...)
2. 네이버 블로그 스마트에디터 ONE에 Ctrl+C / Ctrl+V 또는 원클릭 복사로 바로 붙여넣어도 서식이 깨지지 않는
   화이트 톤(800px 중앙 폭, 네이버 그린 #03C75A 포인트) 인라인 스타일 HTML 생성
3. 20종 도해·차트(나노바나나 AI 과학 도해 4종 + 래스터화 차트 16종)를 네이버 에디터 호환 <img>로 삽입
4. 인터랙티브 웹(chNN_interactive.html)과 순수 복붙 전용(chNN_naver_blog.html) 동시 생성 지원
"""
from __future__ import annotations

import base64
import html
import io
import re
from pathlib import Path
from typing import Any

from PIL import Image


# 단원별 핵심 전문 해시태그 뱅크 (각 단원 고유 주제 + 네이버 농업·과학 검색 키워드)
CHAPTER_HASHTAG_BANK: dict[str, list[str]] = {
    "ch01": [
        "토양유기물", "토양유기탄소", "SOM", "SOC", "POM", "MAOM",
        "입자성유기물", "광물결합유기물", "토양연속체모델", "부식질",
        "토양생태계", "토양건강", "흙토람", "탄소저장", "토양학",
        "토양관리", "친환경농업", "탄소중립농업", "농촌진흥청", "토양비옥도",
    ],
    "ch02": [
        "토양유기물분해", "식물잔사", "근권삼출물", "탄질비", "CN비",
        "유기물동태", "Q10계수", "온도민감도", "토양수분", "호기성분해",
        "혐기성분해", "휴민화계수", "탄소잔존율", "셀룰로오스", "리그닌",
        "토양유기물", "토양학", "농업과학", "유기물관리", "토양미생물",
    ],
    "ch03": [
        "부식화이론", "부식산", "풀빅산", "휴민", "미생물탄소펌프",
        "MCP", "미생물사체", "네크로매스", "토양연속체모델", "광물안정화",
        "점토광물", "산화철복합체", "MAOM", "토양탄소안정화", "부식화학",
        "토양유기물", "토양학", "탄소격리", "유기물형성", "토양생화학",
    ],
    "ch04": [
        "토양물리성", "단립구조", "대단립", "소단립", "단립계층모델",
        "균근균", "글로말린", "유효수분보유능", "AWC", "토양침투율",
        "가뭄저항성", "무경운", "최소경운", "보전경운", "물리적탄소보호",
        "토양유기물", "토양구조개선", "배수개선", "토양학", "농경지관리",
    ],
    "ch05": [
        "토양화학성", "양이온치환용량", "CEC", "부식질전하", "카르복실기",
        "페놀기", "pH완충능", "유기산킬레이트", "인산유효도", "양분보유력",
        "중금속안정화", "토양오염정화", "흡착기작", "비료이용효율", "토양산성화",
        "토양유기물", "토양비옥도", "토양화학", "토양학", "친환경농업",
    ],
    "ch06": [
        "토양미생물", "근권생태계", "근권미생물", "균근균", "AMF",
        "PGPR", "토양지렁이", "토양먹이망", "프라이밍효과", "양성프라이밍",
        "음성프라이밍", "미생물생체량", "MBC", "토양효소활성", "탄소이용효율",
        "CUE", "토양생물학", "토양유기물", "생물다양성", "토양건강",
    ],
    "ch07": [
        "질소동역학", "질소무기화", "질소부동화", "탄질비", "CN화학양론",
        "StanfordSmith모델", "질소순환", "DNDC모델", "DayCent", "아산화질소",
        "질산태질소", "질소용탈", "암모늄태질소", "헤어리베치", "완숙퇴비",
        "토양유기물", "질소비료관리", "온실가스저감", "토양모델링", "농업환경",
    ],
    "ch08": [
        "토양유기탄소분석", "Tyurin법", "WalkleyBlack법", "건식연소법", "Dumas법",
        "강열감량법", "LOI", "VanBemmelen계수", "토양토색판", "SPAD503",
        "E4E6비", "FTIR분광법", "13CNMR", "VisNIR", "토양검정",
        "토양분석법", "국립농업과학원", "토양유기물", "정밀농업", "토양학",
    ],
    "ch09": [
        "토양유기물분획", "물리적분획", "POM", "MAOM", "활성탄소",
        "POXC", "용존유기물", "DOM", "토양건강평가", "흙토람",
        "CornellCASH", "유럽토양건강", "토양질지표", "토양검정", "미생물지표",
        "단립안정성", "토양유기물", "지속가능농업", "농경지진단", "토양학",
    ],
    "ch10": [
        "토양탄소모델", "탄소분해모델", "SoilR", "구획행렬모델", "RothC",
        "CENTURY모델", "DayCent", "MIMICS", "CORPSE모델", "미생물명시형모델",
        "다중풀모델", "DPM", "RPM", "HUM", "IOM",
        "탄소체류시간", "광물포화한계", "토양유기물", "생지화학모델", "기후변화모델",
    ],
    "ch11": [
        "토양탄소모델링", "RothC실습", "DNDC실습", "Python시뮬레이션", "SoilR실습",
        "모델매개변수보정", "민감도분석", "SpinUp", "IOM산정", "장기포장검증",
        "논토양탄소", "밭토양탄소", "시나리오분석", "탄소축적예측", "데이터파이프라인",
        "토양유기물", "농업데이터사이언스", "탄소중립농업", "토양모델", "연구실무",
    ],
    "ch12": [
        "논토양유기물", "밭토양유기물", "시설재배지", "염류집적관리", "토양수분제어",
        "담수토양", "호기성토양", "흙토람기준", "일본MAFF", "시비기준",
        "메탄배출저감", "토양적정기준", "시설원예토양", "농경지유기물", "작물양분관리",
        "토양유기물", "농촌진흥청", "농사로", "스마트팜토양", "토양관리",
    ],
    "ch13": [
        "완숙퇴비", "퇴비부숙도", "녹비작물", "헤어리베치", "작물잔사환원",
        "깊이거름주기", "피복작물", "무경운농업", "윤작체계", "보전농업",
        "USDASARE", "유기물시용", "부식산증진", "탄소중립실증", "토양보전",
        "토양유기물", "친환경농업", "지속가능농업", "농경지관리", "비료관리",
    ],
    "ch14": [
        "바이오차", "Biochar", "열분해온도", "난분해성탄소", "탄소격리",
        "왕겨바이오차", "가축분뇨바이오차", "일본MAFF지침", "부식산자재", "풀빅산자재",
        "식물생장촉진제", "옥신유사활성", "토양개량제", "다공성구조", "양이온치환용량",
        "토양유기물", "저탄소농업", "농림부산물재활용", "친환경자재", "탄소중립",
    ],
    "ch15": [
        "심토유기탄소", "Subsoil", "MAOM미포화", "뿌리탄소", "이탄지",
        "습지토양", "Histosol", "산림토양", "초지토양", "화산회토",
        "Andosol", "비정질광물", "알로페인", "기후온난화피드백", "Q10",
        "토양단면", "특수토양생태계", "토양유기물", "탄소저장고", "생태계보전",
    ],
    "ch16": [
        "기후변화대응", "토양탄소격리", "4per1000", "FAOGSOCseq", "EU토양정책",
        "EJPSOIL", "IPCC인벤토리", "등가토양질량", "ESM", "일본JCredit",
        "저탄소농산물인증", "농업탄소크레딧", "MRV검증", "영속성", "추가성",
        "탄소중립농업", "토양유기물", "기후스마트농업", "ESG농업", "농업정책",
    ],
}

# 소단원 제목·본문 키워드 매핑 (특정 개념이 등장하면 최우선 태그로 반영)
KEYWORD_TO_TAG: list[tuple[str, str]] = [
    ("POM", "POM"),
    ("MAOM", "MAOM"),
    ("MAOC", "MAOC"),
    ("RothC", "RothC"),
    ("CENTURY", "CENTURY모델"),
    ("DayCent", "DayCent"),
    ("DNDC", "DNDC모델"),
    ("MIMICS", "MIMICS"),
    ("CORPSE", "CORPSE모델"),
    ("SoilR", "SoilR"),
    ("Stanford-Smith", "StanfordSmith모델"),
    ("Tyurin", "Tyurin법"),
    ("Walkley-Black", "WalkleyBlack법"),
    ("LOI", "강열감량법"),
    ("SPAD", "SPAD503"),
    ("E4/E6", "E4E6비"),
    ("FTIR", "FTIR분석"),
    ("NMR", "13CNMR"),
    ("POXC", "활성탄소POXC"),
    ("DOM", "용존유기물DOM"),
    ("CASH", "CornellCASH"),
    ("흙토람", "흙토람"),
    ("MAFF", "일본MAFF"),
    ("J-Credit", "일본JCredit"),
    ("4 per 1000", "4per1000"),
    ("MRV", "MRV검증"),
    ("ESM", "등가토양질량"),
    ("바이오차", "바이오차"),
    ("부식산", "부식산"),
    ("풀빅산", "풀빅산"),
    ("휴민", "휴민"),
    ("단립", "토양단립"),
    ("CEC", "양이온치환용량"),
    ("킬레이트", "킬레이트화"),
    ("균근균", "균근균AMF"),
    ("지렁이", "토양지렁이"),
    ("프라이밍", "프라이밍효과"),
    ("무기화", "질소무기화"),
    ("부동화", "질소부동화"),
    ("헤어리베치", "헤어리베치"),
    ("퇴비", "완숙퇴비"),
    ("무경운", "무경운농업"),
    ("보전농업", "보전농업"),
    ("깊이거름주기", "깊이거름주기"),
    ("화산회토", "화산회토"),
    ("이탄지", "이탄지"),
    ("심토", "심토탄소"),
    ("Q10", "Q10온도민감도"),
    ("논토양", "논토양관리"),
    ("시설재배", "시설재배지토양"),
    ("메탄", "메탄저감"),
    ("아산화질소", "아산화질소저감"),
    ("탄소중립", "탄소중립농업"),
    ("탄소격리", "토양탄소격리"),
    ("용어집", "토양학용어집"),
    ("연습문제", "토양학연습문제"),
    ("계산 예제", "토양정량계산"),
    ("실증 사례", "현장실증사례"),
    ("체크리스트", "토양진단체크리스트"),
    ("심화 이론", "토양학심화이론"),
    ("오해와 진실", "토양학오해와진실"),
    ("오해 교정", "토양상식교정"),
]

FALLBACK_TAGS: list[str] = [
    "토양유기물학", "토양학", "토양유기물", "토양탄소", "토양관리",
    "농업과학", "친환경농업", "탄소중립", "지속가능농업", "토양건강",
    "토양비옥도", "농촌진흥청", "흙관리", "작물재배", "스마트농업",
    "농업기술", "토양생태", "기후변화", "환경농학", "전공교재",
]


def _sanitize_tag(tag: str) -> str:
    """네이버 블로그 해시태그 규격(공백·특수문자 제거, 한글/영문/숫자/언더스코어만 허용)으로 정제한다."""
    t = re.sub(r"[^가-힣a-zA-Z0-9_]", "", tag.strip())
    return t[:25]


def generate_20_hashtags(ch_id: str, section_heading: str, section_body: str = "") -> list[str]:
    """소단원 제목·본문·단원 테마를 조합하여 중복 없는 정확히 20개의 네이버 블로그 해시태그를 생성한다."""
    picked: list[str] = []
    seen_lower: set[str] = set()

    def _add(raw_tag: str) -> None:
        t = _sanitize_tag(raw_tag)
        if not t or len(t) < 2:
            return
        low = t.lower()
        if low in seen_lower:
            return
        seen_lower.add(low)
        picked.append(f"#{t}")

    # 1) 소단원 제목에서 매칭되는 도메인 핵심 키워드 최우선 추출 (제목 중심)
    clean_heading = re.sub(r"<[^>]+>", "", section_heading)
    for kw, tag in KEYWORD_TO_TAG:
        if kw.lower() in clean_heading.lower():
            _add(tag)

    # 2) 소단원 본문 앞부분(1500자)에서 추가 매칭되는 도메인 핵심 키워드 보강
    body_head = section_body[:1500]
    for kw, tag in KEYWORD_TO_TAG:
        if kw.lower() in body_head.lower():
            _add(tag)
            if len(picked) >= 12:
                break

    # 3) 해당 단원 전용 해시태그 뱅크 보충
    for t in CHAPTER_HASHTAG_BANK.get(ch_id, []):
        _add(t)
        if len(picked) >= 20:
            break

    # 4) 공통 폴백으로 정확히 20개 보장
    for t in FALLBACK_TAGS:
        if len(picked) >= 20:
            break
        _add(t)

    return picked[:20]


def _encode_visual_for_naver_blog(vis: dict[str, Any]) -> str:
    """네이버 블로그 호환성을 위해 나노바나나 PNG 및 래스터화된 SVG 차트 PNG를 경량 JPEG Data URI <img>로 변환한다."""
    img_path_str = vis.get("docx_image_path") or vis.get("file_path") or ""
    p = Path(img_path_str)
    if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return ""
    img = Image.open(p).convert("RGB")
    max_w = 880
    if img.width > max_w:
        ratio = max_w / img.width
        img = img.resize((max_w, int(img.height * ratio)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def render_naver_figure_html(vis: dict[str, Any]) -> str:
    """네이버 블로그 스마트에디터 ONE 붙여넣기 최적화 도해/차트 블록.
    별도 표나 배지 틀 없이 이미지 바로 아래에 이미지 번호·제목과 자연스러운 줄글 해설 텍스트를 기술한다."""
    fig_no = vis.get("fig_no", "")
    title_ko = vis.get("title_ko") or vis.get("caption_ko", "")
    desc_ko = vis.get("description_ko", "")
    header_line = f"[{fig_no}] {title_ko}" if fig_no else title_ko
    alt_text = html.escape(re.sub(r"\s*\[SRC-[^\]]+\]", "", header_line).strip())
    data_uri = _encode_visual_for_naver_blog(vis)
    if not data_uri:
        return ""
    desc_p = (
        f'<p style="margin:6px 0 0;font-size:14.5px;line-height:1.85;color:#374151;text-align:left;word-break:keep-all;">'
        f"{html.escape(desc_ko)}</p>"
        if desc_ko
        else ""
    )
    return (
        f'<div class="book-figure nb-figure" data-fig-id="{html.escape(vis.get("figure_id", ""))}" '
        f'style="margin:24px 0 26px;text-align:center;">'
        f'<img src="{data_uri}" alt="{alt_text}" style="max-width:100%;width:100%;height:auto;display:block;margin:0 auto 12px;border-radius:6px;border:1px solid #e5e7eb;" />'
        f'<p style="margin:0;font-size:15px;line-height:1.65;color:#111827;font-weight:700;text-align:left;">'
        f"{html.escape(header_line)}</p>"
        f"{desc_p}"
        f"</div>"
    )


# 네이버 블로그 SmartEditor ONE 붙여넣기용 100% 호환 유니코드 위·아래첨자 테이블
# (맑은 고딕·모바일 iOS/Android 기본 폰트에서 깨짐 없이 렌더링되는 문자만 매핑)
_UNI_SUB_MAP = str.maketrans("0123456789+-−", "₀₁₂₃₄₅₆₇₈₉₊₋₋")
_UNI_SUP_MAP = str.maketrans("0123456789+-−=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿ")


def _sub_to_naver_plain(inner: str) -> str:
    txt = re.sub(r"<[^>]+>", "", inner).strip()
    if not txt:
        return ""
    # 순수 숫자/부호 첨자(CO2, CH4, N2O, Q10, N0, C1, K2Cr2O7 등)는 네이티브 유니코드 아래첨자
    if all(ch in "0123456789+-−" for ch in txt):
        return txt.translate(_UNI_SUB_MAP)
    # 영문/복합 아래첨자(k_fast, θ_threshold, ρ_b, C_SOM, M_(OM, input))는 네이버 표에서도 깨지지 않는 _ 표기
    if any(ch in txt for ch in (" ", ",", "+", "-", "−", "/")):
        return f"_({txt})"
    return f"_{txt}"


def _sup_to_naver_plain(inner: str) -> str:
    txt = re.sub(r"<[^>]+>", "", inner).strip()
    if not txt:
        return ""
    # 이온·동위원소·거듭제곱(+, −, 2+, 3+, n+, 13, 2, 3, −1, −10)은 네이티브 유니코드 위첨자
    if all(ch in "0123456789+-−=()n" for ch in txt):
        return txt.translate(_UNI_SUP_MAP)
    # 복합 지수(예: e^(-kt), (n−x)+)는 괄호 ^ 표기
    return f"^({txt})"


def sanitize_math_for_naver_blog(fragment_html: str) -> str:
    """네이버 블로그 SmartEditor ONE 붙여넣기 시 깨지는 LaTeX·CSS 분수·화살표·표 내부 sub/sup를
    100% 깨지지 않는 유니코드·평문 수식 표기로 변환한다."""
    from math_typography import convert_markdown_math_to_html

    s = convert_markdown_math_to_html(fragment_html) if ("$" in fragment_html or "\\" in fragment_html) else fragment_html

    # 1) 세로 분수 <span class="m-frac"> → A / B (또는 (A) / (B))
    def _rep_frac(m: re.Match[str]) -> str:
        num = sanitize_math_for_naver_blog(m.group(1)).strip()
        den = sanitize_math_for_naver_blog(m.group(2)).strip()
        num_plain = re.sub(r"<[^>]+>", "", num).strip()
        den_plain = re.sub(r"<[^>]+>", "", den).strip()
        n_str = num if (len(num_plain) <= 10 and not any(op in num_plain for op in (" + ", " - ", " − ", " × ", " / "))) else f"({num})"
        d_str = den if (len(den_plain) <= 10 and not any(op in den_plain for op in (" + ", " - ", " − ", " × ", " / "))) else f"({den})"
        return f"{n_str} / {d_str}"

    for _ in range(4):
        prev = s
        s = re.sub(
            r'<span class="m-frac"><span class="m-num">([\s\S]*?)</span><span class="m-den">([\s\S]*?)</span></span>',
            _rep_frac,
            s,
        )
        if s == prev:
            break

    # 2) 반응 화살표 <span class="m-rxn"> → —[조건]→
    s = re.sub(
        r'<span class="m-rxn"><span class="m-rxn-lbl">([\s\S]*?)</span><span class="m-rxn-arr">[^<]*</span></span>',
        lambda m: f"—[{sanitize_math_for_naver_blog(m.group(1)).strip()}]→",
        s,
    )

    # 3) <sub> / <sup> → 유니코드 첨자 또는 안전한 _ / ^ 표기
    s = re.sub(r"<sub>([\s\S]*?)</sub>", lambda m: _sub_to_naver_plain(m.group(1)), s)
    s = re.sub(r"<sup>([\s\S]*?)</sup>", lambda m: _sup_to_naver_plain(m.group(1)), s)

    # 4) 표/수식 내 불필요한 math-eq 래퍼 정리 및 미세 오타 보정
    s = s.replace("μ m", "μm")
    return s


def sanitize_tables_for_naver_blog(fragment_html: str) -> str:
    """HTML 조각 내 모든 <table>...</table> 블록 내부의 수식·첨자·분수를 네이버 블로그 호환 형태로 정리한다."""
    return re.sub(
        r"<table\b[\s\S]*?</table>",
        lambda m: sanitize_math_for_naver_blog(m.group(0)),
        fragment_html,
    )


def apply_naver_inline_styles(fragment_html: str, *, full_naver_math: bool = False) -> str:
    """렌더링된 HTML 조각에 네이버 블로그 SmartEditor ONE 붙여넣기용 인라인 스타일을 입힌다.

    - 기본(인터랙티브 웹): 표(<table>) 내부 수식은 네이버 복붙 호환 유니코드/평문으로 즉시 변환하여
      드래그 복사 시에도 표 안 수식이 절대 깨지지 않도록 보장한다.
    - full_naver_math=True(순수 네이버 블로그 HTML): 본문·수식 박스·표 전체의 분수·첨자를
      SmartEditor ONE 100% 호환 유니코드/평문 수식으로 변환한다.
    """
    s = fragment_html
    if full_naver_math:
        s = sanitize_math_for_naver_blog(s)
    else:
        s = sanitize_tables_for_naver_blog(s)
    # CommonMark가 한국어 조사 인접(**용어(영문)**의)으로 미변환한 **볼드** 보정
    s = re.sub(r"\*\*([^*\n<>]+?)\*\*", r"<strong>\1</strong>", s)
    # 오해(Myth) / 진실(Fact) / 현장 교정 포인트 시각 강조
    s = s.replace(
        "<li><strong>오해 (Myth):</strong>",
        '<li style="margin-bottom:8px;padding:8px 12px;background:#fef2f2;border-left:4px solid #ef4444;border-radius:0 6px 6px 0;list-style:none;margin-left:-18px;"><strong style="color:#b91c1c;">❌ 오해 (Myth):</strong>',
    )
    s = s.replace(
        "<li><strong>진실 (Fact):</strong>",
        '<li style="margin-bottom:8px;padding:8px 12px;background:#f0fdf4;border-left:4px solid #03C75A;border-radius:0 6px 6px 0;list-style:none;margin-left:-18px;"><strong style="color:#047857;">✅ 진실 (Fact):</strong>',
    )
    s = s.replace(
        "<li><strong>현장 교정 포인트:</strong>",
        '<li style="margin-bottom:10px;padding:8px 12px;background:#eff6ff;border-left:4px solid #2563eb;border-radius:0 6px 6px 0;list-style:none;margin-left:-18px;"><strong style="color:#1d4ed8;">💡 현장 교정 포인트:</strong>',
    )
    s = re.sub(
        r"<h3(\b[^>]*)>",
        r'<h3\1 style="font-size:17.5px;font-weight:700;color:#0b6b3a;margin:24px 0 10px;line-height:1.5;">',
        s,
    )
    s = re.sub(
        r"<h4(\b[^>]*)>",
        r'<h4\1 style="font-size:15.5px;font-weight:700;color:#1f2937;margin:18px 0 8px;line-height:1.5;">',
        s,
    )
    s = re.sub(
        r"<p>",
        '<p style="margin:0 0 14px;font-size:15.5px;line-height:1.9;color:#222222;word-break:keep-all;">',
        s,
    )
    s = re.sub(
        r"<blockquote>",
        '<blockquote style="margin:16px 0;padding:14px 18px;background:#f4fbf6;border-left:4px solid #03C75A;border-radius:0 8px 8px 0;color:#2d3748;font-size:15px;line-height:1.85;">',
        s,
    )
    s = re.sub(
        r"<ul>",
        '<ul style="margin:0 0 16px;padding-left:22px;font-size:15.5px;line-height:1.85;color:#222222;">',
        s,
    )
    s = re.sub(
        r"<ol>",
        '<ol style="margin:0 0 16px;padding-left:22px;font-size:15.5px;line-height:1.85;color:#222222;">',
        s,
    )
    s = re.sub(r"<li>", '<li style="margin-bottom:6px;">', s)
    s = s.replace(
        "<table>",
        '<div class="table-wrap" style="width:100%;overflow-x:auto;margin:18px 0;"><table class="sortable-table" style="width:100%;border-collapse:collapse;font-size:14px;line-height:1.6;border:1px solid #d1d5db;background:#ffffff;">',
    )
    s = s.replace("</table>", "</table></div>")
    s = re.sub(
        r"<th>",
        '<th style="background:#eef7f1;color:#111827;font-weight:700;padding:10px 12px;border:1px solid #d1d5db;text-align:left;vertical-align:top;">',
        s,
    )
    s = re.sub(
        r"<td>",
        '<td style="padding:9px 12px;border:1px solid #e5e7eb;color:#222222;text-align:left;vertical-align:top;">',
        s,
    )
    s = s.replace(
        '<div class="math-block">',
        '<div class="math-block" style="margin:16px 0;padding:14px 18px;background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #03C75A;border-radius:8px;text-align:center;font-family:\'Cambria Math\',\'Times New Roman\',\'Malgun Gothic\',serif;font-size:16px;line-height:1.85;color:#111827;overflow-x:auto;">',
    )
    s = re.sub(
        r"<pre>",
        '<pre style="background:#f8fafc;color:#1e293b;border:1px solid #cbd5e1;border-radius:8px;padding:14px 16px;overflow-x:auto;max-width:100%;font-size:13px;line-height:1.6;margin:16px 0;">',
        s,
    )
    return s


def render_hashtag_box_html(tags: list[str], section_idx: int) -> str:
    """소단원 말미에 들어갈 관련 해시태그 20개 텍스트 블록 HTML을 생성한다."""
    tags_text = " ".join(tags)
    return (
        f'<div class="nb-hashtag-block" data-sec-idx="{section_idx}" '
        f'style="margin-top:24px;padding:14px 16px;background:#f8fafc;border:1px dashed #cbd5e1;border-radius:8px;">'
        f'<div style="font-size:12.5px;font-weight:700;color:#475569;margin-bottom:6px;">관련 해시태그 (20개)</div>'
        f'<p class="nb-hashtag-text" style="margin:0;font-size:14px;line-height:1.85;color:#03a84e;font-weight:600;word-break:keep-all;">'
        f"{html.escape(tags_text)}</p></div>"
    )
