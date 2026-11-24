"""고품질 한·영 시각화 프롬프트 별도 문서 생성 및 원고 위치 연동 엔진.

저품질 자동 도해·이미지 대신, 그래픽·플로우차트·사실적 이미지·인포그래픽·정량 데이터 그래픽에 대해
한글(KO) 및 영문(EN)으로 매우 치밀한 마스터 프롬프트와 네거티브 프롬프트, 한글 라벨 오버레이 가이드,
Mermaid 플로우차트 코드를 생성하여 별도의 문서(DOCX · Markdown · JSON)로 출력하고,
원고 본문(chapters/chNN.mdx)의 정확한 절 위치에 이미지 번호·연동 코드·상세 설명 앵커 블록을 자동 연동한다.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from compliance import utc_now_iso
from config import PlatformConfig, get_config

# 5대 시각화 유형 마스터 스펙 (사용자 요청: 그래픽, 플로우차트, 사실적 이미지, 인포그래픽 + 정량 데이터 그래픽)
VISUAL_CATEGORIES: dict[str, dict[str, Any]] = {
    "photorealistic": {
        "code": "A",
        "name_ko": "사실적 이미지 (Photorealistic)",
        "name_en": "Photorealistic Editorial Photography",
        "aspect_ratio": "16:9",
        "resolution": "300 DPI · 2400×1350 px (B5 인쇄 폭 152 mm)",
        "recommended_tools": "Google Nano Banana Pro / Imagen 3 / Midjourney v6 / Adobe Firefly",
        "color_note_ko": "자연광 기반 사실적 색감(과채도 금지, 학술 도감 톤)",
        "color_note_en": "natural daylight color grading, documentary agricultural field authenticity, crisp micro-textures",
        "negative_en": (
            "cartoon, illustration, 3D render, CGI plastic look, oversaturated neon, blurry, low resolution, "
            "watermark, stock photo logo, garbled text, gibberish letters, pseudo-Korean glyphs, distorted anatomy, extra limbs"
        ),
    },
    "infographic": {
        "code": "B",
        "name_ko": "인포그래픽 (Infographic)",
        "name_en": "Editorial Scientific Infographic",
        "aspect_ratio": "16:9",
        "resolution": "300 DPI · 2400×1350 px (웹·교재 겸용)",
        "recommended_tools": "Adobe Illustrator / Figma / Canva Pro / Napkin AI + Nano Banana Pro",
        "color_note_ko": "Okabe-Ito 색각 안전 팔레트(#0F2B5B 네이비, #0072B2 블루, #009E73 에메랄드, #E69F00 앰버, #D55E00 버밀리온, 흰색 배경)",
        "color_note_en": "clean Swiss-grid scientific infographic on pure white (#FFFFFF) background, Okabe-Ito colorblind-safe palette (#0F2B5B deep navy, #0072B2 blue, #009E73 teal-green, #E69F00 amber, #D55E00 vermilion)",
        "negative_en": (
            "cluttered layout, dark neon cyberpunk background, overlapping text, illegible gibberish text, "
            "pseudo-Korean characters, 3D glossy clip art, low contrast, watermark, unaligned icons"
        ),
    },
    "flowchart": {
        "code": "C1",
        "name_ko": "플로우차트 (Flowchart)",
        "name_en": "Structured Scientific Process & Decision Flowchart",
        "aspect_ratio": "16:9",
        "resolution": "300 DPI · 2400×1350 px (벡터 SVG/PDF 권장)",
        "recommended_tools": "Mermaid.js / Figma / Lucidchart / Draw.io / Illustrator (수록 Mermaid 코드 즉시 활용)",
        "color_note_ko": "단계별 구분 카드(#E0F2FE 입력, #DCFCE7 처리/제어, #FEF3C7 의사결정 마름모, #FEE2E2 임계 경보, 짙은 회색 화살표 #334155)",
        "color_note_en": "clean flat vector process flowchart on white background, distinct rounded rectangular process nodes, diamond decision gates, crisp directional arrows (#334155), generous negative space",
        "negative_en": (
            "hand-drawn messy sketch, crossing tangled arrows, cramped boxes, garbled text, 3D bevel gradients, "
            "photographic background, watermark, inconsistent font sizes"
        ),
    },
    "graphic_diagram": {
        "code": "C2",
        "name_ko": "과학 그래픽 · 구조 도해 (Scientific Graphic)",
        "name_en": "Publication-Grade Scientific Cross-Section & Mechanism Graphic",
        "aspect_ratio": "3:2",
        "resolution": "300 DPI · 2400×1600 px (Nature/Science 저널 도해 스타일)",
        "recommended_tools": "BioRender / Adobe Illustrator / Nano Banana Pro + Figma 한글 라벨 조판",
        "color_note_ko": "학술 저널 단면·기작 도해 팔레트(부드러운 플랫 셰이딩 + 명확한 외곽선 #1E293B + 고대비 포인트 색상)",
        "color_note_en": "Nature and Science journal style technical vector diagram, clean cutaway cross-section with soft flat shading, sharp dark-slate outlines (#1E293B), numbered callout leader pins on pure white background",
        "negative_en": (
            "messy painting, noisy textures, unreadable AI text labels, pseudo-Korean glyphs, dark cluttered backdrop, "
            "decorative clipart, inaccurate biological proportions, watermark"
        ),
    },
    "data_chart": {
        "code": "D",
        "name_ko": "정량 데이터 그래픽 (Data Visualization)",
        "name_en": "Publication-Grade Quantitative Statistical Graphic",
        "aspect_ratio": "16:9",
        "resolution": "300 DPI · 2400×1350 px (벡터 PDF/SVG · 흑백 인쇄 대응)",
        "recommended_tools": "Python Matplotlib/Seaborn / R ggplot2 / GraphPad Prism / Illustrator",
        "color_note_ko": "Okabe-Ito 색각 안전 5색 + 흑백 인쇄 시 선종류/마커/해칭 구분, 상·우측 스파인 제거",
        "color_note_en": "publication-grade statistical figure (Tufte / Nature style), top and right spines removed, crisp gridlines, Okabe-Ito palette with distinct markers and line styles for grayscale print compatibility",
        "negative_en": (
            "3D pie chart, distorted perspective bars, missing axis units, fabricated numbers, cluttered chartjunk, "
            "low-resolution bitmap text, watermark"
        ),
    },
}

ANCHOR_START_RE = re.compile(r"<!--\s*VISUAL_PROMPT_ANCHOR_START:\s*([A-Z0-9_\-]+)\s*-->")
ANCHOR_BLOCK_RE = re.compile(
    r"\n?<!--\s*VISUAL_PROMPT_ANCHOR_START:\s*[A-Z0-9_\-]+\s*-->[\s\S]*?<!--\s*VISUAL_PROMPT_ANCHOR_END:\s*[A-Z0-9_\-]+\s*-->\n?",
    re.M,
)
SRC_RE = re.compile(r"\bSRC-\d+\b")
HEADING2_RE = re.compile(r"^##\s+(.+?)\s*$")
NUM_UNIT_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?(?:\s*[–\-~]\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:%|°C|℃|mm|cm|m|ha|kg|g|mg/kg|mg/L|μg/L|ug/L|μm|nm|mV|dS/m|pH|kJ/mol|일|시간|배|종|편|건|쪽|mL/g|g/cm³)\b"
)


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        parts = md.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\r\n")
    return md


def _parse_chapter_sections(md_text: str) -> list[dict[str, Any]]:
    """단원 마크다운에서 절(##)별 본문, 표, 수식, 수치, 인용키를 구조화 추출한다."""
    clean = ANCHOR_BLOCK_RE.sub("\n", _strip_frontmatter(md_text))
    lines = clean.splitlines()
    sections: list[dict[str, Any]] = []
    cur_title = ""
    cur_lines: list[str] = []

    def _flush() -> None:
        if not cur_title:
            return
        body = "\n".join(cur_lines).strip()
        if not body:
            return
        # 참고문헌·오해와 진실·연습문제 절은 시각화 기본 대상에서 후순위
        low_t = cur_title.lower()
        if any(k in cur_title for k in ("참고문헌", "연습문제", "이해도 점검")) or "reference" in low_t:
            return
        sids = sorted(set(SRC_RE.findall(body)))
        nums = list(dict.fromkeys(NUM_UNIT_RE.findall(body)))[:10]
        tables: list[list[str]] = []
        cur_tbl: list[str] = []
        for ln in cur_lines:
            st = ln.strip()
            if st.startswith("|") and st.endswith("|"):
                cur_tbl.append(st)
            else:
                if len(cur_tbl) >= 3:
                    tables.append(cur_tbl)
                cur_tbl = []
        if len(cur_tbl) >= 3:
            tables.append(cur_tbl)

        # 핵심 문장 추출 (제목·표·인용구·수식 제외)
        prose_sents: list[str] = []
        for ln in cur_lines:
            st = ln.strip()
            if not st or st.startswith(("#", "|", "```", "$$", "<!--", "---", ">")):
                continue
            cleaned_s = re.sub(r"\*\*([^*]+)\*\*", r"\1", st)
            cleaned_s = re.sub(r"\[[^\]]*SRC-\d+[^\]]*\]", "", cleaned_s).strip()
            if len(cleaned_s) >= 24:
                prose_sents.append(cleaned_s)
        bullets = [re.sub(r"^[-*\d.]+\s*", "", s) for s in prose_sents if len(s) >= 18][:6]
        formulas = re.findall(r"\$\$([\s\S]+?)\$\$", body)[:2]
        sections.append(
            {
                "heading": cur_title,
                "body": body,
                "sids": sids,
                "numbers": nums,
                "tables": tables,
                "formulas": formulas,
                "key_points": bullets,
            }
        )

    for ln in lines:
        m = HEADING2_RE.match(ln.strip())
        if m:
            _flush()
            cur_title = m.group(1).strip()
            cur_lines = []
        elif cur_title:
            cur_lines.append(ln)
    _flush()
    return sections


def _choose_category(sec: dict[str, Any], slot_idx: int, is_paper: bool) -> str:
    """절의 텍스트 신호(표·수치·프로세스·구조·현장)와 균형 배치를 결합해 5대 유형 중 최적 유형을 선택한다."""
    blob = (sec.get("heading", "") + " " + sec.get("body", "")[:600]).lower()
    has_table = bool(sec.get("tables"))
    has_many_nums = len(sec.get("numbers") or []) >= 4

    # 논문 트랙은 사실적 사진보다 정량 그래픽·플로우차트·과학 도해·인포그래픽 우선
    if has_table and has_many_nums and slot_idx % 2 == 0:
        return "data_chart"
    if any(k in blob for k in ("절차", "단계", "알고리즘", "프로세스", "흐름", "모형", "모델", "평가", "판정", "의사결정", "관리", "workflow", "pipeline", "decision", "tier")):
        return "flowchart"
    if any(k in blob for k in ("구조", "기작", "메커니즘", "경로", "대사", "세포", "수용체", "채널", "큐티클", "흡착", "이론", "mechanism", "pathway", "structure", "cutaway")):
        return "graphic_diagram"
    if any(k in blob for k in ("비교", "분류", "지표", "요약", "정책", "기준", "체계", "전략", "comparison", "framework", "classification")):
        return "infographic"
    if not is_paper and any(k in blob for k in ("현장", "포장", "작물", "토양", "생육", "관찰", "장비", "살포", "피해", "병해", "해충", "잡초", "재배", "수확", "저장", "제형", "field", "crop", "soil")):
        return "photorealistic"

    cycle = (
        ["data_chart", "graphic_diagram", "flowchart", "infographic"]
        if is_paper
        else ["graphic_diagram", "flowchart", "infographic", "photorealistic", "data_chart"]
    )
    return cycle[slot_idx % len(cycle)]


def _extract_table_summary(tables: list[list[str]]) -> tuple[str, list[str]]:
    if not tables:
        return "", []
    tbl = tables[0]
    headers = [c.strip().replace("**", "") for c in tbl[0].strip("|").split("|") if c.strip()]
    sample_rows: list[str] = []
    for row_ln in tbl[2:6]:
        cols = [re.sub(r"\*\*|\$|`", "", c.strip()) for c in row_ln.strip("|").split("|")]
        if any(cols):
            sample_rows.append(" | ".join(cols[:4]))
    summary = f"표 항목({', '.join(headers[:5])})" + (f" — 대표 행: {'; '.join(sample_rows[:3])}" if sample_rows else "")
    return summary, headers[:6]


def _extract_korean_labels(sec: dict[str, Any], cat: str) -> list[str]:
    """이미지/도해 위에 후처리 조판할 정확한 한글 라벨 목록(4~6개)을 추출한다."""
    labels: list[str] = []
    heading_clean = re.sub(r"^\d+(?:\.\d+)?\s*", "", sec.get("heading", "")).strip()
    if heading_clean:
        labels.append(f"제목 헤더: {heading_clean[:36]}")
    # 표 헤더 우선
    _, tbl_headers = _extract_table_summary(sec.get("tables") or [])
    for h in tbl_headers[:4]:
        h_clean = re.sub(r"\s+", " ", h).strip()
        if h_clean and len(h_clean) <= 28:
            labels.append(h_clean)
    # 본문 굵은 핵심어 추출
    bolds = re.findall(r"\*\*([^*]{2,26})\*\*", sec.get("body", ""))
    for b in bolds:
        b_clean = re.sub(r"[\$`\[\]]", "", b).strip()
        if b_clean and not b_clean.startswith("SRC-") and b_clean not in labels:
            labels.append(b_clean)
        if len(labels) >= 6:
            break
    if len(labels) < 4:
        for kp in (sec.get("key_points") or [])[:4]:
            short = kp.split(":")[0].split("—")[0].strip()[:24]
            if short and short not in labels:
                labels.append(short)
            if len(labels) >= 5:
                break
    return labels[:6]


def _build_mermaid_code(sec: dict[str, Any], labels: list[str], fig_no: str) -> str:
    """플로우차트/구조 도해용 즉시 렌더링 가능한 Mermaid 코드를 생성한다."""
    nodes = [re.sub(r'["<>`]', "", lb).replace("제목 헤더: ", "").strip()[:28] for lb in labels if lb.strip()]
    if len(nodes) < 3:
        nodes = ["입력 조건 · 현장 관측", "핵심 메커니즘 · 분석 처리", "임계치 판정 · 의사결정", "실행 조치 · 피드백 환류"]
    nodes = nodes[:5]
    lines = ["flowchart LR"]
    for i, lbl in enumerate(nodes, start=1):
        nid = f"N{i}"
        if i == len(nodes) - 1 and len(nodes) >= 4:
            lines.append(f'    {nid}{{"{i}. {lbl}"}}')
        else:
            lines.append(f'    {nid}["{i}. {lbl}"]')
    for i in range(1, len(nodes)):
        lines.append(f"    N{i} --> N{i+1}")
    if len(nodes) >= 3:
        lines.append(f'    N{len(nodes)} -. "검증·피드백" .-> N1')
    return "\n".join(lines)


def _format_source_attribution(sids: list[str], source_map: dict[str, dict[str, Any]], topic_ko: str, cid: str) -> str:
    if not sids:
        return f"자료: 《{topic_ko}》 {cid} 본문 검증 문헌 기반 재구성."
    cited_parts: list[str] = []
    for sid in sids[:4]:
        meta = source_map.get(sid) or {}
        yr = meta.get("year")
        title = str(meta.get("title") or "").strip()
        if title:
            title_s = re.sub(r"^\[\d{4}\]\s*", "", title)[:48]
            cited_parts.append(f"[{sid}] {title_s}" + (f" ({yr})" if yr else ""))
        else:
            cited_parts.append(f"[{sid}]")
    return "자료: " + "; ".join(cited_parts) + " 기반 재구성."


def _compose_bilingual_prompts(
    *,
    topic_ko: str,
    topic_en: str,
    ch_num: int,
    ch_title: str,
    sec: dict[str, Any],
    cat: str,
    fig_no: str,
    prompt_id: str,
    title_ko: str,
    labels_ko: list[str],
    source_note: str,
    output_type: str,
) -> dict[str, str]:
    """도메인 문맥·수치·표·라벨을 모두 반영한 치밀한 한·영 마스터 프롬프트를 생성한다."""
    spec = VISUAL_CATEGORIES[cat]
    sec_heading = sec.get("heading", "")
    key_pts = sec.get("key_points") or []
    pts_ko = "\n".join(f"  - {p[:150]}" for p in key_pts[:4]) or f"  - {ch_title}의 핵심 개념 및 원리 시각화"
    nums = sec.get("numbers") or []
    nums_str = ", ".join(nums[:8]) if nums else "본문 정량 지표 및 기준 임계치 반영"
    tbl_summary, _ = _extract_table_summary(sec.get("tables") or [])
    labels_str = " / ".join(f"({i}) {lb}" for i, lb in enumerate(labels_ko, start=1))
    audience_en = "peer-reviewed academic journal" if output_type == "paper" else "university-level professional textbook"

    # ---- 1) 치밀한 한글 마스터 프롬프트 ----
    if cat == "photorealistic":
        layout_ko = "3분할 황금 구도(Rule of Thirds)의 현장·실험실 사실적 클로즈업/중경 사진. 주 피사체를 선명하게 부각하고 배경은 얕은 피사계 심도(f/2.8~f/4)로 자연스럽게 흐림 처리. 우측 또는 하단에 한글 주석 콜아웃을 얹을 수 있는 정돈된 여백 20% 확보."
        style_ko = "85mm 매크로 또는 35mm 다큐멘터리 렌즈, 오전 자연 확산광(soft morning daylight), 토양·식물 조직·장비 표면의 미세 질감이 살아 있는 고해상도 실사. 과장된 HDR·인공 광택 금지."
    elif cat == "infographic":
        layout_ko = "16:9 가로형 스위스 그리드(Swiss Grid) 에디토리얼 인포그래픽. 상단 제목 헤더(12%) → 중앙 3~4개 핵심 비교 패널·KPI 수치 카드·아이콘 다이어그램(74%) → 하단 출처 바(14%). 패널 간 충분한 여백(최소 24px 상당)으로 시각적 혼잡 차단."
        style_ko = f"플랫 벡터 에디토리얼 디자인, {spec['color_note_ko']}, 단정한 선형 아이콘과 명확한 정보 위계."
    elif cat == "flowchart":
        layout_ko = "좌→우(또는 상→하) 방향의 단계별 의사결정 플로우차트. 입력(둥근 사각형) → 처리·제어 단계(직사각형 카드) → 정량 임계치 판단(마름모 게이트) → 실행 분기(적합/부적합) → 하단 점선 피드백 환류 화살표로 구성."
        style_ko = f"선명한 2D 벡터 다이어그램, {spec['color_note_ko']}, 겹치지 않는 직교 화살표, 균일한 카드 크기."
    elif cat == "graphic_diagram":
        layout_ko = "학술지(Nature/Science) 수준의 단면 절개도(cutaway cross-section) 또는 분자·생리·시스템 기작 도해. 좌측 원리/입력에서 우측 반응/출력으로 자연스럽게 시선이 흐르도록 배치하고, 핵심 부위마다 번호 핀(①~⑥)과 직선 지시선(leader line) 연결."
        style_ko = f"정교한 과학 일러스트레이션, {spec['color_note_ko']}, 절제된 입체 음영과 선명한 경계선."
    else:  # data_chart
        layout_ko = "출판용 정량 통계 그래픽(막대·꺾은선·이중축 또는 범위 비교). X축(범주/조건), Y축(정량 지표 및 단위 명시), 범례는 우상단 여백에 배치, 임계 기준선은 점선으로 표기하고 데이터 레이블을 막대/점 위에 정밀 표시."
        style_ko = f"Tufte/Nature 학술 차트 스타일, {spec['color_note_ko']}, 상단·우측 테두리 제거, 연한 수평 보조선."

    prompt_ko = (
        f"[1. 핵심 주제 및 목적]\n"
        f"- 교재/문서 주제: 《{topic_ko}》 ({ch_title} · {sec_heading})\n"
        f"- 도판 번호 및 제목: {title_ko} (연동 코드: {prompt_id})\n"
        f"- 시각화 유형: {spec['name_ko']}\n\n"
        f"[2. 구도 및 레이아웃 설계]\n"
        f"- {layout_ko}\n\n"
        f"[3. 반드시 표현할 핵심 학술 내용 및 정량 요소]\n"
        f"{pts_ko}\n"
        f"- 반영 핵심 수치·단위: {nums_str}\n"
        + (f"- 원문 표 데이터 연계: {tbl_summary}\n" if tbl_summary else "")
        + f"\n[4. 한글 라벨 및 텍스트 조판 목록 (AI 오타 방지용)]\n"
        f"- 배치할 한글 라벨: {labels_str}\n"
        f"- 표기 원칙: 이미지 생성 시 라벨 영역을 깔끔한 빈 콜아웃 박스(또는 번호 핀 ①~⑥)로 비워 두고, 최종 출판 조판에서 맑은 고딕/Noto Sans KR로 선명하게 한글 라벨을 얹을 것.\n\n"
        f"[5. 스타일 · 색채 · 출력 규격]\n"
        f"- 스타일: {style_ko}\n"
        f"- 규격: {spec['aspect_ratio']} 비율, {spec['resolution']}\n"
        f"- 출처 표기(하단): {source_note}\n"
        f"- 금지 요소: 깨진 한글·알 수 없는 가짜 영문 글자, 워터마크, 근거 없는 임의 수치, 3D 원근 왜곡, 저해상도 흐림."
    )

    # ---- 2) Production-Ready English Master Prompt ----
    sec_en_hint = re.sub(r"[^A-Za-z0-9\s\-/,.:()%+]", " ", f"{topic_en} {sec_heading} {nums_str}")
    sec_en_hint = re.sub(r"\s+", " ", sec_en_hint).strip()[:220] or topic_en or "agricultural science and technology"
    num_pins = len(labels_ko)

    if cat == "photorealistic":
        prompt_en = (
            f"Ultra-detailed editorial scientific photograph for a {audience_en} on '{topic_en or topic_ko}'. "
            f"Subject focus: realistic documentary close-up/medium shot illustrating '{title_ko}' ({sec_en_hint}). "
            f"Shot on professional full-frame DSLR, 85mm f/2.8 macro lens, crisp focus on primary biological/technical textures "
            f"with natural shallow depth-of-field background, soft morning diffused natural daylight, authentic field and laboratory realism, "
            f"rule-of-thirds composition with 20% clean uncluttered breathing space on the right side for editorial callout typesetting. "
            f"{spec['color_note_en']}. Pure visual photography with ZERO embedded text, ZERO letters, and ZERO watermarks. "
            f"Print-ready 300 DPI editorial quality, aspect ratio {spec['aspect_ratio']}."
        )
    elif cat == "infographic":
        prompt_en = (
            f"Publication-grade {spec['name_en']} designed for a {audience_en} about '{topic_en or topic_ko}', "
            f"visualizing '{title_ko}' (key domain context: {sec_en_hint}). "
            f"Structured 16:9 Swiss-grid multi-panel layout: clean navy header bar at top, {max(3, min(4, num_pins))} evenly spaced visual comparison modules "
            f"with minimalist custom vector icons, structured KPI metric badges, subtle directional connectors, and a clean bottom citation strip. "
            f"{spec['color_note_en']}. Generous whitespace, razor-sharp vector geometry, flat modern editorial aesthetic. "
            f"CRITICAL TYPOGRAPHY RULE: Leave clean blank callout rectangles or minimal numbered badges (1 to {num_pins}) with ZERO garbled text or pseudo-characters, "
            f"so crisp Korean publication labels can be overlaid cleanly in final layout. 300 DPI vector print quality, aspect ratio {spec['aspect_ratio']}."
        )
    elif cat == "flowchart":
        prompt_en = (
            f"Publication-grade {spec['name_en']} for a {audience_en} on '{topic_en or topic_ko}', "
            f"depicting the structured step-by-step workflow and decision logic of '{title_ko}' ({sec_en_hint}). "
            f"Horizontal left-to-right orthogonal layout with {max(4, min(6, num_pins))} color-coded rounded process cards, "
            f"an explicit diamond decision gate for threshold evaluation, clear pass/fail action branches, and a dashed bottom feedback return arrow. "
            f"{spec['color_note_en']}. Balanced margins, strictly non-overlapping orthogonal connectors, crisp 2D flat vector precision. "
            f"CRITICAL TYPOGRAPHY RULE: Use clean empty framed label boxes with minimal numeric step markers (01–0{max(4, min(6, num_pins))}) and NO garbled text, "
            f"ready for crisp Korean typography overlay. 300 DPI vector quality, aspect ratio {spec['aspect_ratio']}."
        )
    elif cat == "graphic_diagram":
        prompt_en = (
            f"High-precision {spec['name_en']} for a {audience_en} on '{topic_en or topic_ko}', "
            f"illustrating the scientific mechanism, anatomical/system cross-section, and functional pathways of '{title_ko}' ({sec_en_hint}). "
            f"Clean left-to-right visual flow showing layered structural cutaway view, zoomed molecular/micro-interface inset panel, "
            f"directional process arrows, and {num_pins} clean numbered callout leader pins pointing accurately to key components. "
            f"{spec['color_note_en']}. Pure white background, balanced editorial composition, Nature/Science magazine visual clarity. "
            f"CRITICAL TYPOGRAPHY RULE: Show ONLY clean numbered pins (1–{num_pins}) and blank leader callout zones with ZERO AI-generated gibberish text, "
            f"allowing spotless Korean scientific typesetting. 300 DPI print-ready illustration, aspect ratio {spec['aspect_ratio']}."
        )
    else:  # data_chart
        prompt_en = (
            f"Publication-grade {spec['name_en']} (Nature / Science journal standard) for a {audience_en} on '{topic_en or topic_ko}', "
            f"presenting quantitative empirical comparison for '{title_ko}' ({sec_en_hint}). "
            f"Clean 2D grouped bar or dual-axis line plot on pure white background, top and right axis spines removed, "
            f"subtle horizontal reference gridlines, distinct threshold dashed reference line, clear legend in upper-right whitespace, "
            f"and bottom citation footer space. {spec['color_note_en']}. "
            f"CRITICAL DATA INTEGRITY RULE: Preserve exact empirical proportions from verified source data only, no decorative 3D distortion, "
            f"clean uncluttered axis ticks ready for Korean axis labels. 300 DPI vector chart standard, aspect ratio {spec['aspect_ratio']}."
        )

    detailed_desc_ko = (
        f"본 도판({fig_no}, 연동 코드 {prompt_id})은 「{sec_heading}」 절의 핵심 내용을 독자가 직관적으로 이해하도록 기획된 "
        f"{spec['name_ko']}이다. "
        + (f"본문의 핵심 내용({key_pts[0][:110]})을 중심으로 " if key_pts else "")
        + (f"정량 지표({', '.join(nums[:5])})와 " if nums else "")
        + f"핵심 요소({', '.join(labels_ko[:4])})의 관계를 명확한 시각 위계로 구조화한다. ({source_note})"
    )

    return {
        "prompt_ko": prompt_ko,
        "prompt_en": prompt_en,
        "negative_prompt_en": spec["negative_en"],
        "detailed_description_ko": detailed_desc_ko,
    }


def _enhance_prompt_with_local_llm(
    item: dict[str, Any],
    sec_body: str,
    cfg: PlatformConfig,
) -> None:
    """선택 옵션(use_llm_enhance=True) 시 로컬 Ollama Gemma 4로 영문·한글 프롬프트의 구체적 시각 묘사를 1회 정교화한다."""
    try:
        from local_gemma import LocalGemmaClient

        client = LocalGemmaClient(cfg)
        sys_p = (
            "You are a world-class Nature/Science visual art director and prompt engineer. "
            "Given a textbook/paper section and a base visual prompt, return a JSON object with keys "
            "'prompt_ko' (detailed Korean visual direction) and 'prompt_en' (ultra-crisp English prompt for Midjourney/Imagen/Illustrator, "
            "keeping NO garbled text rule). Return valid JSON only."
        )
        usr_p = (
            f"Title: {item['title_ko']}\nCategory: {item['category_name_ko']}\n"
            f"Section excerpt:\n{sec_body[:1200]}\n\n"
            f"Base prompt_en:\n{item['prompt_en']}\n"
        )
        resp = client.chat_json(
            system=sys_p,
            user=usr_p,
            schema={
                "type": "object",
                "properties": {
                    "prompt_ko": {"type": "string"},
                    "prompt_en": {"type": "string"},
                },
                "required": ["prompt_ko", "prompt_en"],
            },
            timeout=45,
        )
        if isinstance(resp, dict):
            if len(str(resp.get("prompt_ko") or "").strip()) >= 80:
                item["prompt_ko"] = str(resp["prompt_ko"]).strip()
            if len(str(resp.get("prompt_en") or "").strip()) >= 80:
                item["prompt_en"] = str(resp["prompt_en"]).strip()
            item["llm_enhanced"] = True
    except Exception:
        item["llm_enhanced"] = False


def inject_visual_anchors_into_chapters(
    project_id: str,
    items: list[dict[str, Any]],
    prompt_docx_filename: str,
    *,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """각 단원 원고(chapters/chNN.mdx)의 정확한 절 위치에 이미지 번호·연동 코드·상세 설명 앵커 블록을 안전(멱등) 삽입한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    ch_dir = Path(st["workspace_dir"]) / "chapters"
    if not ch_dir.is_dir():
        return {"updated_chapters": 0, "anchors_inserted": 0}

    by_ch: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_ch.setdefault(str(it["chapter_id"]), []).append(it)

    hist_dir = ch_dir / "_history"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    updated_chapters = 0
    anchors_inserted = 0

    for cid, ch_items in sorted(by_ch.items()):
        p = ch_dir / f"{cid}.mdx"
        if not p.is_file():
            continue
        orig = p.read_text(encoding="utf-8", errors="ignore")
        # 기존 프롬프트 연동 앵커 블록을 먼저 깔끔히 제거 (멱등성 보장: 중복 삽입 절대 방지)
        cleaned = ANCHOR_BLOCK_RE.sub("\n", orig)
        lines = cleaned.splitlines()

        # 절별 삽입 대상 맵 구성
        inserts_after_line: dict[int, list[str]] = {}
        fallback_blocks: list[str] = []

        for it in ch_items:
            pid_code = it["prompt_id"]
            fig_no = it["figure_no"]
            cat_ko = it["category_name_ko"]
            sec_h = it["target_section"]
            block = (
                f"\n<!-- VISUAL_PROMPT_ANCHOR_START: {pid_code} -->\n"
                f"> **🖼️ [도판 삽입 위치 · {fig_no} | 연동 코드: `{pid_code}` | 유형: {cat_ko}]**\n"
                f"> - **도판 제목**: {it['title_ko']}\n"
                f"> - **삽입 위치**: {it['chapter_title']} — {sec_h}\n"
                f"> - **상세 설명**: {it['detailed_description_ko']}\n"
                f"> - **자료 출처**: {it['source_note']}\n"
                f"> - **연동 프롬프트 문서**: `{prompt_docx_filename}` (`{pid_code}` 항목 — 한글·영문 마스터 프롬프트 수록) · 업로드 파일명 규격: `{it['filename']}`\n"
                f"<!-- VISUAL_PROMPT_ANCHOR_END: {pid_code} -->\n"
            )

            # 매칭되는 ## 절 제목을 찾아 그 절의 첫 문단 뒤(또는 다음 ## 직전)에 삽입
            match_idx = -1
            for li, ln in enumerate(lines):
                m = HEADING2_RE.match(ln.strip())
                if m and (m.group(1).strip() == sec_h or sec_h[:16] in m.group(1).strip()):
                    match_idx = li
                    break

            if match_idx >= 0:
                # 해당 절 내부 끝(다음 ##/### 직전)을 찾아 자연스럽게 배치
                insert_pos = match_idx
                for j in range(match_idx + 1, len(lines)):
                    s_ln = lines[j].strip()
                    if s_ln.startswith("## "):
                        break
                    if s_ln:
                        insert_pos = j
                inserts_after_line.setdefault(insert_pos, []).append(block)
            else:
                fallback_blocks.append(block)
            anchors_inserted += 1

        new_lines: list[str] = []
        for idx, ln in enumerate(lines):
            new_lines.append(ln)
            if idx in inserts_after_line:
                for blk in inserts_after_line[idx]:
                    new_lines.append(blk)

        if fallback_blocks:
            # 참고문헌 직전에 삽입
            ref_pos = next((i for i, l in enumerate(new_lines) if l.strip().startswith("### 참고문헌")), len(new_lines))
            new_lines = new_lines[:ref_pos] + fallback_blocks + new_lines[ref_pos:]

        updated_text = "\n".join(new_lines).rstrip() + "\n"
        if updated_text != orig:
            hist_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, hist_dir / f"{cid}_pre_prompt_anchor_{ts}.mdx")
            p.write_text(updated_text, encoding="utf-8")
            updated_chapters += 1

    return {"updated_chapters": updated_chapters, "anchors_inserted": anchors_inserted}


def _render_prompt_pack_markdown(pack: dict[str, Any]) -> str:
    """복사·붙여넣기 최적화 마크다운 프롬프트 마스터 문서를 생성한다."""
    lines = [
        f"# {pack['topic_ko']} — 고품질 한·영 시각화 프롬프트 마스터 문서",
        "",
        f"- **프로젝트 ID**: `{pack['project_id']}`",
        f"- **생성 시각**: {pack['generated_at']}",
        f"- **총 시각화 기획 수**: {pack['total_prompts']}종 (사실적 이미지 · 인포그래픽 · 플로우차트 · 과학 그래픽 · 정량 데이터 그래픽)",
        f"- **원고 연동 상태**: 본문 각 단원(`.mdx` / 마스터 DOCX / 블로그 HTML)의 정확한 절 위치에 `[연동 코드 · 그림 번호 · 상세 설명]` 자동 삽입됨",
        "",
        "## 0. 전체 도판 · 원고 위치 연동 색인표",
        "",
        "| 연동 코드 | 그림 번호 | 원고 삽입 위치 (단원 · 절) | 시각화 유형 | 도판 제목 | 업로드 파일명 |",
        "|---|---|---|---|---|---|",
    ]
    for it in pack["items"]:
        lines.append(
            f"| `{it['prompt_id']}` | **{it['figure_no']}** | {it['chapter_id']} · {it['target_section']} | {it['category_name_ko']} | {it['title_ko']} | `{it['filename']}` |"
        )
    lines.append("")

    cur_ch = ""
    for it in pack["items"]:
        if it["chapter_id"] != cur_ch:
            cur_ch = it["chapter_id"]
            lines.extend(["---", "", f"## {it['chapter_title']} (`{cur_ch}`)", ""])
        lines.extend(
            [
                f"### [{it['prompt_id']}] {it['title_ko']}",
                "",
                f"- **시각화 유형**: {it['category_name_ko']} (`{it['category_code']}`)",
                f"- **원고 삽입 위치**: `{it['chapter_id']}` — {it['target_section']}",
                f"- **권장 판형 · 해상도**: {it['aspect_ratio']} · {it['resolution']}",
                f"- **권장 제작 도구**: {it['recommended_tools']}",
                f"- **완성 이미지 업로드 파일명**: `{it['filename']}` (대시보드 [🖼️ 이미지 스튜디오]에서 해당 그림 번호에 업로드 시 원고 자동 결합)",
                f"- **상세 설명**: {it['detailed_description_ko']}",
                f"- **자료 출처**: {it['source_note']}",
                f"- **한글 라벨 오버레이 목록**: " + " / ".join(it.get("korean_labels") or []),
                "",
                "#### 🇰🇷 한글 마스터 프롬프트 (Korean Master Prompt)",
                "```text",
                it["prompt_ko"],
                "```",
                "",
                "#### 🇺🇸 영문 마스터 프롬프트 (English Master Prompt — Midjourney / Nano Banana Pro / Imagen / Illustrator)",
                "```text",
                it["prompt_en"],
                "```",
                "",
                "#### 🚫 네거티브 프롬프트 (Negative Prompt)",
                "```text",
                it["negative_prompt_en"],
                "```",
                "",
            ]
        )
        if it.get("mermaid_code"):
            lines.extend(
                [
                    "#### 📐 즉시 렌더링 가능 Mermaid 플로우차트 코드",
                    "```mermaid",
                    it["mermaid_code"],
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def _render_prompt_pack_docx(pack: dict[str, Any], out_docx: Path) -> None:
    """출판급 B5/A4 별책 시각화 프롬프트 마스터 DOCX를 생성한다 (math_typography 적용 · 수식 누수 0건)."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Mm, Pt, RGBColor
    from math_typography import add_rich_runs_to_docx_paragraph

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width = Mm(210)
    sec.page_height = Mm(297)
    sec.top_margin = Mm(18)
    sec.bottom_margin = Mm(18)
    sec.left_margin = Mm(16)
    sec.right_margin = Mm(16)
    sec.different_first_page_header_footer = True

    hdr_p = sec.header.paragraphs[0]
    hdr_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    add_rich_runs_to_docx_paragraph(
        hdr_p,
        f"{pack['topic_ko']} — 고품질 한·영 시각화 프롬프트 마스터 문서",
        font_size=8.2,
        color_rgb=(71, 85, 105),
    )

    def _shade(cell, hex_color: str) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>'))

    def _pad(cell, t=65, b=65, l=90, r=90) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        m = OxmlElement("w:tcMar")
        for s, v in (("top", t), ("bottom", b), ("left", l), ("right", r)):
            n = OxmlElement(f"w:{s}")
            n.set(qn("w:w"), str(v))
            n.set(qn("w:type"), "dxa")
            m.append(n)
        tcPr.append(m)

    def _borders(tbl, color="CBD5E1", top_bot="0F2B5B") -> None:
        tbl._tbl.tblPr.append(
            parse_xml(
                f'<w:tblBorders {nsdecls("w")}>'
                f'<w:top w:val="single" w:sz="8" w:space="0" w:color="{top_bot}"/>'
                f'<w:bottom w:val="single" w:sz="8" w:space="0" w:color="{top_bot}"/>'
                f'<w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
                f'<w:left w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
                f'<w:right w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
                f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="{color}"/>'
                f"</w:tblBorders>"
            )
        )

    def _p(container, text: str, *, size=9.2, rgb=(30, 41, 59), bold=False, align=WD_ALIGN_PARAGRAPH.LEFT, sb=0, sa=3, ls=1.3, first=False):
        p = container.paragraphs[0] if first else container.add_paragraph()
        p.alignment = align
        p.paragraph_format.space_before = Pt(sb)
        p.paragraph_format.space_after = Pt(sa)
        p.paragraph_format.line_spacing = ls
        add_rich_runs_to_docx_paragraph(p, text, font_size=size, color_rgb=rgb, base_bold=bold)
        return p

    # ---- 표지 & 활용 가이드 ----
    _p(doc, "", sb=24, sa=4)
    _p(doc, "전문 출판 시각화 기획 별책 · 본문 삽입 위치 자동 연동", size=10.5, rgb=(14, 90, 111), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, sa=8)
    _p(doc, f"《{pack['topic_ko']}》\n고품질 한·영 시각화 프롬프트 마스터북", size=21.0, rgb=(15, 43, 91), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, sa=8, ls=1.35)
    _p(doc, "Bilingual (Korean & English) Visual Prompt Specification — Linked to Manuscript Positions", size=10.5, rgb=(71, 85, 105), align=WD_ALIGN_PARAGRAPH.CENTER, sa=18)

    # 요약 박스
    cat_counts = pack.get("category_counts") or {}
    cat_line = " · ".join(f"{VISUAL_CATEGORIES[k]['name_ko'].split(' (')[0]} {v}종" for k, v in cat_counts.items() if k in VISUAL_CATEGORIES)
    guide_tbl = doc.add_table(rows=4, cols=2)
    guide_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(guide_tbl)
    g_rows = [
        ("총 시각화 기획 수", f"{pack['total_prompts']}종 ({cat_line})"),
        ("원고 본문 연동 방식", "원고 각 단원·절의 정확한 위치에 [도판 삽입 위치 · 그림 번호 · 연동 코드(VP-CHNN-MM) · 상세 설명] 블록 자동 삽입"),
        ("권장 이미지 제작 워크플로", "① 영문 마스터 프롬프트 + 네거티브 프롬프트로 고해상도 이미지 생성(Midjourney/Nano Banana Pro/Imagen/Illustrator) → ② '한글 라벨 오버레이 목록'으로 선명한 한글 조판 → ③ 지정 파일명(fig_chNN_vMM.png)으로 저장"),
        ("대시보드 자동 결합", "완성 이미지를 대시보드 [🖼️ 이미지 스튜디오]의 동일 그림 번호에 업로드하면 마스터 DOCX·블로그 HTML에 즉시 반영됩니다."),
    ]
    for r_i, (k, v) in enumerate(g_rows):
        c0, c1 = guide_tbl.rows[r_i].cells
        _shade(c0, "EEF2FF")
        _shade(c1, "FFFFFF")
        _pad(c0)
        _pad(c1)
        c0.width = Mm(46)
        c1.width = Mm(132)
        _p(c0, k, size=8.8, rgb=(15, 43, 91), bold=True, first=True, sa=0)
        _p(c1, v, size=8.6, rgb=(30, 41, 59), first=True, sa=0)

    # ---- 0. 전체 색인표 ----
    doc.add_page_break()
    _p(doc, "0. 전체 도판 · 원고 삽입 위치 연동 색인표", size=13.0, rgb=(15, 43, 91), bold=True, sa=6)
    idx_tbl = doc.add_table(rows=len(pack["items"]) + 1, cols=6)
    idx_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(idx_tbl)
    hdrs = ["연동 코드", "그림 번호", "원고 위치", "유형", "도판 제목", "파일명 규격"]
    hrow = idx_tbl.rows[0]
    hrow._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    widths = [24, 18, 36, 26, 48, 26]
    for ci, h in enumerate(hdrs):
        cell = hrow.cells[ci]
        _shade(cell, "0F2B5B")
        _pad(cell, 55, 55, 55, 55)
        cell.width = Mm(widths[ci])
        _p(cell, h, size=8.0, rgb=(255, 255, 255), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, first=True, sa=0)

    for r_i, it in enumerate(pack["items"], start=1):
        row = idx_tbl.rows[r_i]
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        bg = "F8FAFC" if r_i % 2 == 0 else "FFFFFF"
        vals = [
            it["prompt_id"],
            it["figure_no"],
            f"{it['chapter_id']} · {it['target_section'][:22]}",
            it["category_name_ko"].split(" (")[0],
            it["title_ko"][:38],
            it["filename"],
        ]
        for ci, val in enumerate(vals):
            cell = row.cells[ci]
            _shade(cell, bg)
            _pad(cell, 45, 45, 50, 50)
            cell.width = Mm(widths[ci])
            _p(
                cell,
                val,
                size=7.6,
                rgb=(15, 43, 91) if ci in (0, 1) else (30, 41, 59),
                bold=(ci in (0, 1)),
                align=WD_ALIGN_PARAGRAPH.CENTER if ci in (0, 1, 3) else WD_ALIGN_PARAGRAPH.LEFT,
                first=True,
                sa=0,
                ls=1.15,
            )

    # ---- 단원별 상세 프롬프트 카드 ----
    cur_ch = ""
    for it in pack["items"]:
        if it["chapter_id"] != cur_ch:
            cur_ch = it["chapter_id"]
            doc.add_page_break()
            _p(doc, f"{it['chapter_title']} ({cur_ch})", size=13.5, rgb=(15, 43, 91), bold=True, sa=8)

        _p(doc, f"[{it['prompt_id']}] {it['title_ko']}", size=11.0, rgb=(14, 90, 111), bold=True, sb=6, sa=3)
        card = doc.add_table(rows=7 + (1 if it.get("mermaid_code") else 0), cols=2)
        card.alignment = WD_TABLE_ALIGNMENT.CENTER
        _borders(card, color="CBD5E1", top_bot="0E5A6F")

        rows_data = [
            ("삽입 위치 · 규격", f"원고 위치: {it['chapter_id']} ({it['target_section']}) | 유형: {it['category_name_ko']} | 규격: {it['aspect_ratio']} ({it['resolution']}) | 파일명: {it['filename']}"),
            ("상세 설명 · 출처", f"{it['detailed_description_ko']}\n[출처] {it['source_note']}"),
            ("한글 라벨 오버레이", " / ".join(it.get("korean_labels") or [])),
            ("권장 제작 도구", it["recommended_tools"]),
            ("🇰🇷 한글 마스터 프롬프트", it["prompt_ko"]),
            ("🇺🇸 English Master Prompt", it["prompt_en"]),
            ("🚫 Negative Prompt", it["negative_prompt_en"]),
        ]
        if it.get("mermaid_code"):
            rows_data.append(("📐 Mermaid 코드", it["mermaid_code"]))

        for r_i, (label, val) in enumerate(rows_data):
            row = card.rows[r_i]
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            c0, c1 = row.cells
            c0.width = Mm(38)
            c1.width = Mm(140)
            _shade(c0, "F1F5F9" if r_i < 4 else ("EFF6FF" if r_i == 4 else ("ECFDF5" if r_i == 5 else "FEF2F2")))
            _shade(c1, "FFFFFF" if r_i < 4 else "F8FAFC")
            _pad(c0, 50, 50, 65, 65)
            _pad(c1, 50, 50, 75, 75)
            c0.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            c1.vertical_alignment = WD_ALIGN_VERTICAL.TOP
            _p(c0, label, size=8.1, rgb=(15, 43, 91), bold=True, first=True, sa=0, ls=1.18)
            _p(c1, val, size=8.2, rgb=(30, 41, 59), first=True, sa=0, ls=1.25)

    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))


def build_project_visual_prompt_pack(
    project_id: str,
    *,
    per_chapter_count: int | None = None,
    inject_manuscript_anchors: bool = True,
    update_visuals_plan: bool = True,
    use_llm_enhance: bool = False,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """프로젝트 전 단원에 대한 고품질 한·영 시각화 프롬프트 별도 문서(DOCX/MD/JSON)를 생성하고 원고 위치와 연동한다."""
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    ch_dir = ws / "chapters"
    assets_dir = ws / "assets"
    exports_dir = ws / "exports"
    assets_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    opts = st.get("options") or {}
    if per_chapter_count is None:
        raw_per = opts.get("visuals_per_chapter")
        per_chapter_count = max(1, min(12, int(4 if raw_per is None else raw_per)))
    else:
        per_chapter_count = max(1, min(12, int(per_chapter_count)))

    otype = st.get("primary_output_type") or (st.get("output_profile") or {}).get("primary_output_type") or "textbook"
    is_paper = otype == "paper"
    topic_ko = str(st.get("topic_ko") or project_id)
    topic_en = str(st.get("topic_en") or topic_ko)

    # 근거 출처 메타 매핑 (collected_sources + evidence_packet)
    source_map: dict[str, dict[str, Any]] = {}
    for s in st.get("collected_sources") or []:
        if s.get("source_id"):
            source_map[str(s["source_id"])] = s
    ev_pkt = cfg.evidence_dir / f"{st.get('packet_id') or project_id}_evidence.json"
    if ev_pkt.is_file():
        try:
            ev_data = json.loads(ev_pkt.read_text(encoding="utf-8"))
            for s in ev_data.get("sources") or []:
                if s.get("source_id") and str(s["source_id"]) not in source_map:
                    source_map[str(s["source_id"])] = s
        except Exception:
            pass

    # 청사진 로드 (단원 제목·순서 확보)
    bp_p = ws / "blueprints" / "master_outline.yaml"
    bp_chapters: dict[str, dict[str, Any]] = {}
    ordered_cids: list[str] = []
    if bp_p.is_file():
        bp = yaml.safe_load(bp_p.read_text(encoding="utf-8")) or {}
        for pt in bp.get("parts") or []:
            for ch in pt.get("chapters") or []:
                cid = str(ch.get("chapter_id") or "")
                if cid:
                    bp_chapters[cid] = ch
                    ordered_cids.append(cid)

    mdx_files = sorted(ch_dir.glob("*.mdx")) if ch_dir.is_dir() else []
    for p in mdx_files:
        if p.stem not in ordered_cids:
            ordered_cids.append(p.stem)
    if not ordered_cids:
        ordered_cids = [f"ch{i:02d}" for i in range(1, max(2, int(st.get("chapter_count") or 4)) + 1)]

    items: list[dict[str, Any]] = []
    cat_counts: dict[str, int] = {}

    for ch_idx, cid in enumerate(ordered_cids, start=1):
        m_num = re.search(r"(\d+)", cid)
        ch_num = int(m_num.group(1)) if m_num else ch_idx
        bp_ch = bp_chapters.get(cid) or {}
        ch_title = str(bp_ch.get("title") or f"제{ch_num}장")
        mdx_p = ch_dir / f"{cid}.mdx"

        sections: list[dict[str, Any]] = []
        if mdx_p.is_file():
            raw_md = mdx_p.read_text(encoding="utf-8", errors="ignore")
            m_h1 = re.search(r"^#\s+(.+?)\s*$", _strip_frontmatter(raw_md), re.M)
            if m_h1:
                ch_title = m_h1.group(1).strip()
            sections = _parse_chapter_sections(raw_md)

        # 아직 집필 전이면 청사진 절(sections) 기반으로 초안 프롬프트 생성
        if not sections:
            bp_secs = bp_ch.get("sections") or [f"{ch_num}.1 핵심 개념 및 구조", f"{ch_num}.2 메커니즘 및 적용"]
            summary_ko = str(bp_ch.get("summary_ko") or f"{ch_title} 핵심 내용")
            for s_name in bp_secs:
                sections.append(
                    {
                        "heading": str(s_name),
                        "body": summary_ko,
                        "sids": list(source_map.keys())[:3],
                        "numbers": [],
                        "tables": [],
                        "formulas": [],
                        "key_points": [summary_ko],
                    }
                )

        # 단원당 목표 개수만큼 절 균등 배분
        selected_secs: list[dict[str, Any]] = []
        for slot in range(per_chapter_count):
            selected_secs.append(sections[slot % len(sections)])

        for v_idx, sec in enumerate(selected_secs, start=1):
            cat = _choose_category(sec, v_idx - 1, is_paper)
            spec = VISUAL_CATEGORIES[cat]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

            fig_id = f"fig_{cid}_v{v_idx:02d}"
            fig_no = f"그림 {ch_num}-{v_idx}"
            prompt_id = f"VP-{cid.upper()}-{v_idx:02d}"
            sec_clean = re.sub(r"^\d+(?:\.\d+)?\s*", "", sec["heading"]).strip()
            title_ko = f"{fig_no}. {sec_clean[:44]}"
            labels_ko = _extract_korean_labels(sec, cat)
            sids = sec.get("sids") or list(source_map.keys())[:3]
            source_note = _format_source_attribution(sids, source_map, topic_ko, cid)

            composed = _compose_bilingual_prompts(
                topic_ko=topic_ko,
                topic_en=topic_en,
                ch_num=ch_num,
                ch_title=ch_title,
                sec=sec,
                cat=cat,
                fig_no=fig_no,
                prompt_id=prompt_id,
                title_ko=title_ko,
                labels_ko=labels_ko,
                source_note=source_note,
                output_type=otype,
            )

            rec: dict[str, Any] = {
                "prompt_id": prompt_id,
                "figure_id": fig_id,
                "figure_no": fig_no,
                "chapter_id": cid,
                "chapter_number": ch_num,
                "chapter_title": ch_title,
                "index": v_idx,
                "target_section": sec["heading"],
                "category": cat,
                "category_code": spec["code"],
                "category_name_ko": spec["name_ko"],
                "category_name_en": spec["name_en"],
                "title_ko": title_ko,
                "aspect_ratio": spec["aspect_ratio"],
                "resolution": spec["resolution"],
                "recommended_tools": spec["recommended_tools"],
                "filename": f"{fig_id}.png",
                "korean_labels": labels_ko,
                "source_ids": sids[:6],
                "data_source": source_note,
                "source_note": source_note,
                "detailed_description_ko": composed["detailed_description_ko"],
                "narrative_ko": composed["detailed_description_ko"],
                "prompt_ko": composed["prompt_ko"],
                "prompt_en": composed["prompt_en"],
                "negative_prompt_en": composed["negative_prompt_en"],
                "mermaid_code": _build_mermaid_code(sec, labels_ko, fig_no) if cat in ("flowchart", "graphic_diagram") else "",
                "status": "PROMPT_READY",
                "engine": "Bilingual Prompt Pack (0원)",
                "is_ai_image": False,
                "exclude_from_publish": False,
                "llm_enhanced": False,
            }
            if use_llm_enhance:
                _enhance_prompt_with_local_llm(rec, sec.get("body", ""), cfg)
            items.append(rec)

    docx_name = f"{project_id}_visual_prompts.docx"
    md_name = f"{project_id}_visual_prompts.md"
    docx_path = exports_dir / docx_name
    md_path = exports_dir / md_name
    json_path = assets_dir / "visual_prompt_pack.json"

    pack_payload: dict[str, Any] = {
        "project_id": project_id,
        "topic_ko": topic_ko,
        "topic_en": topic_en,
        "primary_output_type": otype,
        "generated_at": utc_now_iso(),
        "total_prompts": len(items),
        "per_chapter_count": per_chapter_count,
        "category_counts": cat_counts,
        "docx_filename": docx_name,
        "md_filename": md_name,
        "docx_path": str(docx_path),
        "md_path": str(md_path),
        "docx_url": f"/project-files/{project_id}/exports/{docx_name}",
        "md_url": f"/project-files/{project_id}/exports/{md_name}",
        "items": items,
    }

    # 1) 별도 프롬프트 마스터 문서(MD + DOCX + JSON) 저장 & E 드라이브 미러링
    md_text = _render_prompt_pack_markdown(pack_payload)
    md_path.write_text(md_text, encoding="utf-8")
    _render_prompt_pack_docx(pack_payload, docx_path)
    json_path.write_text(json.dumps(pack_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        e_exp = cfg.project_e_exports_dir(project_id)
        e_exp.mkdir(parents=True, exist_ok=True)
        shutil.copy2(docx_path, e_exp / docx_name)
        shutil.copy2(md_path, e_exp / md_name)
        e_vis = cfg.e_projects_dir / project_id / "visuals"
        e_vis.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json_path, e_vis / "visual_prompt_pack.json")
    except Exception:
        pass

    # 2) 원고 본문에 [이미지 번호 · 연동 코드 · 상세 설명] 앵커 블록 자동 삽입
    anchor_res = {"updated_chapters": 0, "anchors_inserted": 0}
    if inject_manuscript_anchors:
        anchor_res = inject_visual_anchors_into_chapters(project_id, items, docx_name, cfg=cfg)
        pack_payload["anchor_sync"] = anchor_res
        json_path.write_text(json.dumps(pack_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) visuals_plan.json 동기화 (prompt_pack_only 모드일 때 5/6단계 품질 게이트 연동)
    if update_visuals_plan:
        plan_p = assets_dir / "visuals_plan.json"
        if opts.get("visual_generation_mode") == "prompt_pack_only" or not plan_p.is_file():
            plan_payload = {
                "project_id": project_id,
                "topic_ko": topic_ko,
                "generated_at": pack_payload["generated_at"],
                "prompt_pack_mode": True,
                "total_visuals": len(items),
                "per_chapter_target": per_chapter_count,
                "ai_images_count": 0,
                "prompt_pack_docx_url": pack_payload["docx_url"],
                "prompt_pack_md_url": pack_payload["md_url"],
                "visuals": items,
            }
            plan_p.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (assets_dir / "visuals_text_guide.md").write_text(md_text, encoding="utf-8")

    # 4) state.json 에 프롬프트 문서 메타 & 다운로드 경로 기록
    st_fresh = load_project_state(project_id, cfg) or st
    st_fresh["visual_prompt_pack"] = {
        "total_prompts": len(items),
        "category_counts": cat_counts,
        "docx_url": pack_payload["docx_url"],
        "md_url": pack_payload["md_url"],
        "docx_path": str(docx_path),
        "md_path": str(md_path),
        "docx_size_kb": round(docx_path.stat().st_size / 1024, 1),
        "anchors_inserted": anchor_res["anchors_inserted"],
        "updated_chapters": anchor_res["updated_chapters"],
        "generated_at": pack_payload["generated_at"],
    }
    outs = dict(st_fresh.get("outputs") or {})
    outs["visual_prompts_docx"] = pack_payload["docx_url"]
    outs["visual_prompts_md"] = pack_payload["md_url"]
    st_fresh["outputs"] = outs
    save_project_state(st_fresh, cfg)

    append_event(
        project_id,
        "visual-artist",
        "stage5_visuals_generate",
        f"📝 고품질 한·영 시각화 프롬프트 마스터 문서 생성 완료: {len(items)}종 "
        f"({docx_name}, {round(docx_path.stat().st_size / 1024, 1)} KB · 원고 앵커 {anchor_res['anchors_inserted']}곳 연동)",
        cfg=cfg,
    )
    return {
        "status": "OK",
        "project_id": project_id,
        "total_prompts": len(items),
        "category_counts": cat_counts,
        "docx_url": pack_payload["docx_url"],
        "md_url": pack_payload["md_url"],
        "docx_path": str(docx_path),
        "md_path": str(md_path),
        "docx_size_kb": round(docx_path.stat().st_size / 1024, 1),
        "anchor_sync": anchor_res,
        "pack": pack_payload,
    }


def load_project_visual_prompt_pack(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")
    jp = Path(st["workspace_dir"]) / "assets" / "visual_prompt_pack.json"
    if not jp.is_file():
        return {"exists": False, "project_id": project_id, "total_prompts": 0, "items": []}
    data = json.loads(jp.read_text(encoding="utf-8"))
    data["exists"] = True
    return data
