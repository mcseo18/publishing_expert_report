"""참참살이 영농 AI 출판도우미 — 기본 2종 출판기(PDF + 블로그용 단일 HTML) 및 사후 포맷 변환 모듈.

설계 원칙 (산출물 중복 제거):
1. 기본 출판(`publish_default_outputs`)은 정확히 2개의 핵심 산출물만 생성한다:
   - ① 마스터 PDF 1종 (`exports/<pid>_master.pdf`)
     * `paper`(논문·리뷰)인 경우: 국내 학회지 논문 규격(KCI 등재 농학계 학회지 표준 — A4, 상하 25mm/좌우 20mm,
       1단 전폭 표제·단일 초록 박스, 본문 2단 편집, 3선표, 명조 9.2pt, 내어쓰기 단일 통합 참고문헌) 자동 적용
     * 그 외 유형: 1차 산출물 권장 판형(교과서 B5, 이야기책 신국판, 보고서/강의/웹 A4) 자동 적용
   - ② 블로그용 단일 HTML 1종 (`exports/<pid>_blog_single.html`)
     * 전체 원고(ch01~chNN)와 시각화를 1개 HTML 파일로 통합, 네이버 스마트에디터 ONE 복붙 최적화 및 원클릭 복사 버튼 포함

2. 추가 포맷 사후 변환 모듈(`convert_project_output`)은 사용자가 필요할 때만 개별 실행한다:
   - `docx`               : MS Word 마스터 합본 (.docx)
   - `korean_journal_pdf` : 국내 학회지 논문 규격 2단 PDF (A4)
   - `b5_pdf`             : B5 대학교재 합본 PDF (182×257mm)
   - `shinkuk_pdf`        : 신국판 단행본 합본 PDF (152×225mm)
   - `a4_pdf`             : A4 표준 합본 PDF (210×297mm)
   - `markdown_master`    : 단일 통합 마크다운 (.md)
   - `chapter_split_html` : 단원별 분할 블로그/웹 HTML 묶음
   - `quarto_book`        : Quarto 싱글소스 프로젝트 (_quarto.yml + .qmd)
   - `cover_toc`          : 별도 표지 · 머리말 · 전체 목차 패키지

CLI 사용 예:
    .venv\\Scripts\\python.exe scripts\\output_converter.py --project <pid> --default-only
    .venv\\Scripts\\python.exe scripts\\output_converter.py --project <pid> --format docx
    .venv\\Scripts\\python.exe scripts\\output_converter.py --project <pid> --format korean_journal_pdf
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config import PlatformConfig, get_config


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# 1. 국내 학회지 논문 규격 PDF 표준 명세 (KCI 농학계 학회지 표준)
# ============================================================
KOREAN_JOURNAL_PDF_SPEC: dict[str, Any] = {
    "id": "korean_journal_a4",
    "label_ko": "국내 학회지 논문 규격 PDF (A4 · 1단 표제/초록 · 본문 2단 · 3선표)",
    "reference_journals": [
        "한국작물학회지 (Korean Journal of Crop Science)",
        "한국농림기상학회지 (Korean Journal of Agricultural and Forest Meteorology)",
        "한국토양비료학회지 (Korean Journal of Soil Science and Fertilizer)",
        "한국원예학회지 (Horticultural Science and Technology)",
    ],
    "page_size": "210mm 297mm",
    "margin": "25mm 20mm 25mm 20mm",
    "body_font": "'KoPubWorldBatang', 'KoPubBatang', 'Batang', 'Malgun Gothic', serif",
    "heading_font": "'KoPubWorldDotum', 'Pretendard', 'Malgun Gothic', sans-serif",
    "body_pt": "9.2pt",
    "line_height": "1.55",
    "column_count": 2,
    "column_gap": "7mm",
    "three_line_table": True,
}

# ============================================================
# 2. 사후 포맷 변환 모듈 카탈로그 (필요 시에만 변환)
# ============================================================
CONVERSION_FORMATS: dict[str, dict[str, str]] = {
    "docx": {
        "id": "docx",
        "icon": "📝",
        "name_ko": "MS Word 합본 (DOCX)",
        "description_ko": "편집·심사·출판사 투고용 단일 Word(.docx) 마스터 문서로 변환합니다.",
        "ext": ".docx",
    },
    "korean_journal_pdf": {
        "id": "korean_journal_pdf",
        "icon": "📄",
        "name_ko": "국내 학회지 논문 규격 PDF",
        "description_ko": "A4 2단 편집 · 1단 전폭 표제/초록 · 3선표 · 내어쓰기 참고문헌 규격 PDF로 변환합니다.",
        "ext": ".pdf",
    },
    "b5_pdf": {
        "id": "b5_pdf",
        "icon": "📗",
        "name_ko": "B5 대학교재 판형 PDF",
        "description_ko": "182×257mm 대학 전공 교재 표준 인쇄판 PDF로 변환합니다.",
        "ext": ".pdf",
    },
    "shinkuk_pdf": {
        "id": "shinkuk_pdf",
        "icon": "📕",
        "name_ko": "신국판 단행본 PDF",
        "description_ko": "152×225mm 일반 단행본·POD(부크크/교보) 출판용 PDF로 변환합니다.",
        "ext": ".pdf",
    },
    "a4_pdf": {
        "id": "a4_pdf",
        "icon": "📘",
        "name_ko": "A4 표준 보고서·강의 PDF",
        "description_ko": "210×297mm 1단 A4 보고서·강의안 표준 PDF로 변환합니다.",
        "ext": ".pdf",
    },
    "markdown_master": {
        "id": "markdown_master",
        "icon": "📋",
        "name_ko": "단일 통합 마크다운 (.md)",
        "description_ko": "전체 원고를 1개의 순수 Markdown(.md) 파일로 합쳐 외부 편집기/노션/깃허브에 활용합니다.",
        "ext": ".md",
    },
    "chapter_split_html": {
        "id": "chapter_split_html",
        "icon": "🌐",
        "name_ko": "단원별 분할 블로그 HTML 묶음",
        "description_ko": "단일 HTML 대신 각 장(ch01~chNN)별 개별 네이버 블로그 연재용 HTML로 분할 변환합니다.",
        "ext": ".html",
    },
    "quarto_book": {
        "id": "quarto_book",
        "icon": "⚙️",
        "name_ko": "Quarto 싱글소스 프로젝트",
        "description_ko": "_quarto.yml 및 각 장 .qmd 소스를 생성해 LaTeX/Quarto 정밀 조판으로 확장합니다.",
        "ext": ".yml",
    },
    "cover_toc": {
        "id": "cover_toc",
        "icon": "🎨",
        "name_ko": "표지 · 머리말 · 전체 목차 별도 패키지",
        "description_ko": "독립 표지 아트(SVG)와 머리말·전체 목차(HTML/PDF/DOCX/MD)를 필요 시 생성합니다.",
        "ext": ".html",
    },
}


def _load_project_chapters(ws: Path) -> list[dict[str, Any]]:
    from build_outputs import _parse_frontmatter

    ch_dir = ws / "chapters"
    if not ch_dir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for idx, p in enumerate(sorted(ch_dir.glob("*.mdx")), 1):
        raw = p.read_text(encoding="utf-8", errors="ignore")
        meta, body = _parse_frontmatter(raw)
        items.append(
            {
                "index": idx,
                "chapter_id": p.stem,
                "path": p,
                "meta": meta,
                "title": str(meta.get("title") or p.stem),
                "chapter_role": str(meta.get("chapter_role") or "").strip().lower(),
                "body": body,
            }
        )
    return items


def _strip_leading_h1(body_md: str) -> str:
    return re.sub(r"^\s*#\s+[^\n]+\n*", "", body_md, count=1).strip()


def _extract_journal_paper_parts(chapters: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """논문·리뷰 단원 목록을 초록(1단 전폭) / 본문(2단) / 참고문헌(최하단 내어쓰기)으로 분류한다."""
    from output_type_profiles import infer_paper_section_role

    abstract_chs: list[dict[str, Any]] = []
    body_chs: list[dict[str, Any]] = []
    ref_chs: list[dict[str, Any]] = []
    total = len(chapters)
    for ch in chapters:
        role = infer_paper_section_role(
            {"chapter_role": ch.get("chapter_role"), "title": ch.get("title")},
            idx=ch["index"],
            total=total,
        )
        ch["resolved_role"] = role
        if role == "abstract":
            abstract_chs.append(ch)
        elif role == "references":
            ref_chs.append(ch)
        else:
            body_chs.append(ch)
    return {"abstract": abstract_chs, "body": body_chs, "references": ref_chs}


def render_korean_journal_html(
    state: dict[str, Any],
    chapters: list[dict[str, Any]],
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """국내 학회지 논문 투고 규격(KCI 농학계 학회지 표준) HTML/CSS를 생성한다.

    규격 핵심:
    - A4 (210×297mm), 여백 상하 25mm / 좌우 20mm, 상단 러닝헤더, 하단 중앙 `- N -` 쪽번호
    - 1단 전폭 표제부: 논문 유형 배지, 국문 제목(16pt Bold), 영문 제목(12pt), 저자/소속/교신저자
    - 1단 전폭 단일 초록 박스: 상하 실선 경계 + 국·영문 Abstract 및 Keywords 단 1회
    - 본문 2단 편집 (`column-count: 2; column-gap: 7mm`): 재료 및 방법 · 결과 및 고찰 · 핵심 내용 요약
    - 표(3선표)·그림·대제목은 `column-span: all` 적용으로 레이아웃 깨짐 방지
    - 참고문헌은 최하단에 내어쓰기(hanging indent)로 단 1회 통합 수록
    """
    from build_outputs import MD_PARSER, _clean_mdx_artifacts, _highlight_citations_html
    from figure_registry import figure_css, inject_figures_into_chapter_html
    from math_typography import math_typography_css
    from output_type_profiles import resolve_output_profile

    prof = resolve_output_profile("paper", state.get("output_profile"))
    topic_ko = str(state.get("topic_ko") or "학술 논문").strip()
    topic_en = str(state.get("topic_en") or "").strip()
    paper_type = str(prof.get("paper_type") or "체계적 문헌고찰 / 리뷰 논문 (Review Paper)")
    journal_tier = str(prof.get("journal_tier") or "KCI 등재지 · 국내 학회지 투고 규격")
    is_review = ("리뷰" in paper_type) or ("Review" in paper_type) or ("고찰" in paper_type)
    kicker_type = "총설 (Review Article)" if is_review else "원저 (Original Article)"
    short_running = (topic_ko[:34] + "…") if len(topic_ko) > 35 else topic_ko
    pub_year = datetime.now().strftime("%Y")
    pub_date = datetime.now().strftime("%Y. %m. %d.")
    author_line = str((state.get("cover_settings") or {}).get("author") or "참참살이 영농 AI 연구집필위원회*")
    affil_line = str((state.get("cover_settings") or {}).get("publisher") or "참참살이 영농 AI 연구소 (Agro AI Publishing Lab)")

    grouped = _extract_journal_paper_parts(chapters)

    # 1. 단일 초록 (1단 전폭)
    abstract_blocks: list[str] = []
    for ch in grouped["abstract"]:
        cid = ch["chapter_id"]
        clean = _clean_mdx_artifacts(_strip_leading_h1(ch["body"]))
        ch_html = _highlight_citations_html(MD_PARSER.render(clean))
        abstract_blocks.append(ch_html)
    abstract_html = "\n".join(abstract_blocks) if abstract_blocks else (
        f"<p>본 논문은 {html.escape(topic_ko)}에 관한 국내외 1차 연구 근거를 체계적으로 분석하고 정량적·기작적 고찰을 제시한다.</p>"
    )

    # 2. 본문 2단 영역 (2. 재료 및 방법, 3. 결과 및 고찰, 4. 핵심 내용 요약)
    body_blocks: list[str] = []
    for ch in grouped["body"]:
        cid = ch["chapter_id"]
        clean = _clean_mdx_artifacts(ch["body"])
        ch_html = _highlight_citations_html(MD_PARSER.render(clean))
        if visuals_map and cid in visuals_map:
            ch_html = inject_figures_into_chapter_html(cid, ch_html, visuals_map, theme="print")
        role_cls = ch.get("resolved_role", "body")
        body_blocks.append(f"<section class='journal-section role-{html.escape(role_cls)}' id='{html.escape(cid)}'>{ch_html}</section>")

    # 3. 최하단 단일 참고문헌 (내어쓰기)
    ref_blocks: list[str] = []
    for ch in grouped["references"]:
        clean = _clean_mdx_artifacts(ch["body"])
        ref_html = _highlight_citations_html(MD_PARSER.render(clean))
        ref_blocks.append(f"<section class='journal-references' id='{html.escape(ch['chapter_id'])}'>{ref_html}</section>")

    css = f"""
    @page {{
      size: {KOREAN_JOURNAL_PDF_SPEC['page_size']};
      margin: {KOREAN_JOURNAL_PDF_SPEC['margin']};
      @top-left {{
        content: "{html.escape(kicker_type)}";
        font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
        font-size: 7.8pt;
        color: #475569;
      }}
      @top-right {{
        content: "{html.escape(short_running)}";
        font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
        font-size: 7.8pt;
        color: #475569;
      }}
      @bottom-center {{
        content: "- " counter(page) " -";
        font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
        font-size: 8.5pt;
        color: #1e293b;
      }}
    }}
    @page :first {{
      @top-left {{ content: none; }}
      @top-right {{ content: none; }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['body_font']};
      font-size: {KOREAN_JOURNAL_PDF_SPEC['body_pt']};
      line-height: {KOREAN_JOURNAL_PDF_SPEC['line_height']};
      color: #111827;
      margin: 0;
    }}
    /* 표제부 (국내 학회지 1단 전폭) */
    .journal-masthead {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1.5pt solid #111827;
      padding-bottom: 4px;
      margin-bottom: 14px;
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 8pt;
      color: #334155;
    }}
    .journal-type-pill {{
      font-weight: 700;
      color: #063b2c;
      letter-spacing: 0.4px;
    }}
    .title-block {{
      text-align: center;
      margin-bottom: 14px;
    }}
    .title-ko {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 16pt;
      font-weight: 800;
      line-height: 1.35;
      color: #0f172a;
      margin: 0 0 6px;
      border: none;
      padding: 0;
    }}
    .title-en {{
      font-family: 'Times New Roman', Georgia, serif;
      font-size: 11.5pt;
      font-weight: 600;
      color: #334155;
      margin: 0 0 10px;
      line-height: 1.35;
    }}
    .author-block {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 9.2pt;
      color: #1e293b;
      margin-bottom: 3px;
    }}
    .affil-block {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 8pt;
      color: #475569;
    }}
    /* 단일 전체 초록 박스 (1단 전폭, 상하 실선) */
    .abstract-box {{
      border-top: 1.5pt solid #1e293b;
      border-bottom: 1.5pt solid #1e293b;
      background: #fafafa;
      padding: 10px 14px;
      margin: 12px 0 16px;
      font-size: 8.6pt;
      line-height: 1.52;
      text-align: justify;
    }}
    .abstract-box-title {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 9.5pt;
      font-weight: 800;
      text-align: center;
      letter-spacing: 1px;
      color: #0f172a;
      margin: 0 0 6px;
    }}
    .abstract-box h2 {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 8.8pt;
      font-weight: 700;
      color: #0f172a;
      border: none;
      padding: 0;
      margin: 8px 0 3px;
    }}
    .abstract-box p {{
      margin: 3px 0 6px;
      text-indent: 0;
    }}
    /* 본문 2단 편집 (국내 학회지 표준) */
    .journal-two-col {{
      column-count: {KOREAN_JOURNAL_PDF_SPEC['column_count']};
      column-gap: {KOREAN_JOURNAL_PDF_SPEC['column_gap']};
      text-align: justify;
      word-break: keep-all;
      overflow-wrap: break-word;
    }}
    .journal-two-col p {{
      margin: 0 0 6px;
      text-indent: 1em;
    }}
    .journal-two-col ul, .journal-two-col ol {{
      margin: 4px 0 8px;
      padding-left: 16px;
    }}
    .journal-two-col li {{
      margin-bottom: 3px;
      text-indent: 0;
    }}
    .journal-section h1 {{
      column-span: all;
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 11.5pt;
      font-weight: 800;
      color: #0f172a;
      border-bottom: 1pt solid #0f172a;
      padding-bottom: 3px;
      margin: 14px 0 8px;
      page-break-after: avoid;
      break-after: avoid;
    }}
    .journal-section h2 {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 9.8pt;
      font-weight: 700;
      color: #0f172a;
      margin: 10px 0 5px;
      padding-left: 0;
      border: none;
      page-break-after: avoid;
      break-after: avoid;
    }}
    .journal-section h3 {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 9.2pt;
      font-weight: 700;
      color: #1e293b;
      margin: 8px 0 4px;
      page-break-after: avoid;
      break-after: avoid;
    }}
    .journal-section blockquote {{
      background: #f8fafc;
      border-left: 2.5pt solid #063b2c;
      padding: 6px 9px;
      margin: 7px 0;
      font-size: 8.6pt;
    }}
    .journal-section blockquote p {{
      text-indent: 0;
    }}
    /* 학술지 표준 3선표 (Three-line Table) — 전폭 배치로 깨짐 방지 */
    .journal-two-col table {{
      column-span: all;
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0 12px;
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 8pt;
      line-height: 1.42;
      border-top: 1.5pt solid #111827;
      border-bottom: 1.5pt solid #111827;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .journal-two-col thead th {{
      background: #f8fafc;
      color: #0f172a;
      font-weight: 700;
      padding: 5px 6px;
      border-bottom: 0.75pt solid #111827;
      border-left: none;
      border-right: none;
      text-align: left;
    }}
    .journal-two-col tbody td {{
      padding: 4.5px 6px;
      border: none;
      border-bottom: 0.35pt solid #e2e8f0;
      vertical-align: top;
      text-align: left;
    }}
    .journal-two-col tbody tr:last-child td {{
      border-bottom: none;
    }}
    .journal-two-col figure, .journal-two-col .fig-card {{
      column-span: all;
      margin: 10px auto 12px;
      page-break-inside: avoid;
      break-inside: avoid;
    }}
    .cite-tag {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 7.8pt;
      font-weight: 600;
      color: #063b2c;
    }}
    /* 최하단 단일 참고문헌 (1단 전폭 또는 2단 내어쓰기) */
    .journal-references {{
      margin-top: 14px;
      border-top: 1pt solid #94a3b8;
      padding-top: 8px;
      font-size: 8.1pt;
      line-height: 1.48;
    }}
    .journal-references h1 {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 11pt;
      font-weight: 800;
      color: #0f172a;
      border-bottom: 1pt solid #0f172a;
      padding-bottom: 3px;
      margin: 4px 0 8px;
    }}
    .journal-references h2 {{
      font-family: {KOREAN_JOURNAL_PDF_SPEC['heading_font']};
      font-size: 8.8pt;
      font-weight: 700;
      color: #334155;
      margin: 4px 0 6px;
    }}
    .journal-references ol, .journal-references ul {{
      list-style: none;
      padding-left: 0;
      margin: 0;
    }}
    .journal-references li, .journal-references p {{
      padding-left: 1.8em;
      text-indent: -1.8em;
      margin: 0 0 4px;
      text-align: left;
      word-break: break-word;
    }}
    .journal-references blockquote {{
      display: none;
    }}
    {figure_css("print")}
    {math_typography_css("print")}
    """

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<title>{html.escape(topic_ko)} · 국내 학회지 논문 규격</title>
<style>{css}</style>
</head>
<body>
  <div class="journal-masthead">
    <span class="journal-type-pill">{html.escape(kicker_type)}</span>
    <span>{html.escape(journal_tier)} · {pub_year} ({pub_date})</span>
  </div>

  <header class="title-block">
    <h1 class="title-ko">{html.escape(topic_ko)}</h1>
    {f'<div class="title-en">{html.escape(topic_en)}</div>' if topic_en else ''}
    <div class="author-block">{html.escape(author_line)}</div>
    <div class="affil-block">{html.escape(affil_line)} (*Corresponding Author · Agro AI Publishing Platform)</div>
  </header>

  <section class="abstract-box">
    <div class="abstract-box-title">초 록 · ABSTRACT</div>
    {abstract_html}
  </section>

  <main class="journal-two-col">
    {''.join(body_blocks)}
  </main>

  {''.join(ref_blocks)}
</body>
</html>"""


def render_standard_master_html(
    state: dict[str, Any],
    chapters: list[dict[str, Any]],
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
    trim_key: str = "b5",
) -> str:
    """교과서(B5)·이야기책(신국판)·보고서/강의(A4)용 단일 마스터 PDF HTML을 생성한다."""
    from agro_framework import BRAND_IDENTITY, MULTI_TRIM_SPECS
    from build_outputs import MD_PARSER, _clean_mdx_artifacts, _highlight_citations_html
    from figure_registry import figure_css, inject_figures_into_chapter_html
    from math_typography import math_typography_css

    spec = MULTI_TRIM_SPECS.get(trim_key, MULTI_TRIM_SPECS["b5"])
    topic_ko = str(state.get("topic_ko") or state.get("project_id") or "전문 교재").strip()
    topic_en = str(state.get("topic_en") or "").strip()
    audience = str(state.get("target_audience") or "대학 전공 심화, 연구자 및 현장 실무자")
    otype_name = str((state.get("output_profile") or {}).get("output_type_name_ko") or "전문 출판물")

    toc_items: list[str] = []
    ch_blocks: list[str] = []
    for ch in chapters:
        cid = ch["chapter_id"]
        toc_items.append(
            f"<li><span class='toc-cid'>{html.escape(cid.upper())}</span> {html.escape(ch['title'])}</li>"
        )
        clean = _clean_mdx_artifacts(ch["body"])
        ch_html = _highlight_citations_html(MD_PARSER.render(clean))
        if visuals_map and cid in visuals_map:
            ch_html = inject_figures_into_chapter_html(cid, ch_html, visuals_map, theme="print")
        ch_blocks.append(f"<section class='chapter-block' id='{html.escape(cid)}'>{ch_html}</section>")

    css = f"""
    @page {{
      size: {spec['page_size']};
      margin: {spec['margin']};
      @top-right {{ content: "{html.escape(topic_ko)} · {html.escape(spec['label_ko'])}"; font-size: 8pt; color: #64748b; }}
      @bottom-center {{ content: counter(page); font-size: 8.5pt; color: #1D3557; }}
    }}
    body {{ font-family: {BRAND_IDENTITY['typography']['body_print']}; font-size: {spec['body_pt']}; line-height: 1.72; color: #1e293b; margin: 0; }}
    .master-cover {{ background: linear-gradient(155deg, #063b2c 0%, #0f291e 55%, #1D3557 100%); color: #fff; padding: 34mm 20mm; border-radius: 8px; page-break-after: always; }}
    .master-cover .kicker {{ color: #34d399; font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: 9pt; letter-spacing: 1.5px; font-weight: 700; }}
    .master-cover h1 {{ color: #fff; font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: 22pt; border: none; margin: 12px 0 8px; }}
    .master-cover .en {{ color: #fef08a; font-size: 11pt; margin-bottom: 18px; }}
    .master-cover .rule {{ width: 64px; height: 3px; background: #eab308; margin: 16px 0; }}
    .master-toc {{ page-break-after: always; }}
    .master-toc h2 {{ color: #1D3557; border-left: 4px solid #eab308; padding-left: 10px; }}
    .master-toc ul {{ list-style: none; padding: 0; }}
    .master-toc li {{ padding: 6px 0; border-bottom: 1px dotted #cbd5e1; font-size: 9.5pt; }}
    .toc-cid {{ display: inline-block; width: 46px; font-weight: 700; color: #063b2c; }}
    .chapter-block {{ page-break-before: always; }}
    h1 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: {spec['h1_pt']}; color: #1D3557; border-bottom: 2px solid #063b2c; padding-bottom: 5px; }}
    h2 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; font-size: {spec['h2_pt']}; color: #1D3557; border-left: 4px solid #eab308; padding-left: 9px; page-break-after: avoid; }}
    h3 {{ font-family: {BRAND_IDENTITY['typography']['heading_print']}; color: #063b2c; page-break-after: avoid; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 8.2pt; }}
    th {{ background: #1D3557; color: #fff; padding: 5px 7px; border: 1px solid #cbd5e1; }}
    td {{ padding: 5px 7px; border: 1px solid #cbd5e1; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    blockquote {{ background: #f8fafc; border-left: 4px solid #063b2c; padding: 10px 14px; margin: 12px 0; }}
    .cite-tag {{ color: #063b2c; background: #ecfdf5; border: 1px solid #a7f3d0; padding: 0 3px; border-radius: 3px; font-size: 7.8pt; font-weight: 700; }}
    {figure_css("print")}
    {math_typography_css("print")}
    """

    return (
        f"<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'><title>{html.escape(topic_ko)}</title><style>{css}</style></head><body>"
        f"<section class='master-cover'>"
        f"<div class='kicker'>참참살이 영농 AI 출판도우미 · {html.escape(otype_name)}</div>"
        f"<h1>{html.escape(topic_ko)}</h1>"
        f"<div class='en'>{html.escape(topic_en)}</div>"
        f"<div class='rule'></div>"
        f"<div style='font-size:9.5pt;line-height:1.9'><div><b>인쇄 판형:</b> {html.escape(spec['label_ko'])}</div>"
        f"<div><b>대상 독자:</b> {html.escape(audience)}</div>"
        f"<div><b>수록 분량:</b> 총 {len(chapters)}개 구성 · 발행일 {datetime.now().strftime('%Y-%m-%d')}</div></div>"
        f"</section>"
        f"<section class='master-toc'><h2>전체 목차 (Table of Contents)</h2><ul>{''.join(toc_items)}</ul></section>"
        f"{''.join(ch_blocks)}</body></html>"
    )


def render_single_blog_html(
    state: dict[str, Any],
    chapters: list[dict[str, Any]],
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """전체 원고를 네이버 블로그(SmartEditor ONE)·웹 발행에 최적화된 단일 HTML 1개 파일로 통합 렌더링한다."""
    from build_outputs import MD_PARSER, _clean_mdx_artifacts, _highlight_citations_html
    from figure_registry import figure_css, inject_figures_into_chapter_html
    from naver_blog_formatter import (
        apply_naver_inline_styles,
        generate_20_hashtags,
        render_hashtag_box_html,
        sanitize_math_for_naver_blog,
    )

    topic_ko = str(state.get("topic_ko") or state.get("project_id") or "전문 콘텐츠").strip()
    topic_en = str(state.get("topic_en") or "").strip()
    otype = str(state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook")
    otype_name = str((state.get("output_profile") or {}).get("output_type_name_ko") or "전문 출판물")
    kws_ko = [str(k).strip() for k in (state.get("keywords_ko") or []) if str(k).strip()]

    toc_links: list[str] = []
    article_sections: list[str] = []
    combined_plain_for_tags: list[str] = [topic_ko, " ".join(kws_ko)]

    for ch in chapters:
        cid = ch["chapter_id"]
        title = ch["title"]
        toc_links.append(
            f"<li style='margin:4px 0'><a href='#sec-{html.escape(cid)}' style='color:#065f46;text-decoration:none;font-weight:600'>{html.escape(title)}</a></li>"
        )
        clean = sanitize_math_for_naver_blog(_clean_mdx_artifacts(ch["body"]))
        combined_plain_for_tags.append(clean[:600])
        rendered = _highlight_citations_html(MD_PARSER.render(clean))
        if visuals_map and cid in visuals_map:
            rendered = inject_figures_into_chapter_html(cid, rendered, visuals_map, theme="web")
        styled = apply_naver_inline_styles(rendered)
        article_sections.append(
            f"<article id='sec-{html.escape(cid)}' style='margin:28px 0 36px;padding-bottom:20px;border-bottom:1px dashed #cbd5e1'>{styled}</article>"
        )

    # 블로그 하단 20개 핵심 해시태그 생성 (주제 키워드 우선 반영)
    raw_tags = generate_20_hashtags(
        "ch01",
        topic_ko,
        " ".join(combined_plain_for_tags)[:3000],
    )
    # 프로젝트 고유 키워드를 앞쪽에 우선 배치하여 20개 맞춤
    custom_tags: list[str] = []
    for kw in [topic_ko] + kws_ko:
        cleaned_tag = re.sub(r"[^0-9A-Za-z가-힣]", "", kw)
        if cleaned_tag and cleaned_tag not in custom_tags:
            custom_tags.append(cleaned_tag)
    for t in raw_tags:
        clean_t = t.lstrip("#").strip()
        if clean_t and clean_t not in custom_tags:
            custom_tags.append(clean_t)
    final_20_tags = [f"#{t}" for t in custom_tags[:20]]
    tag_box_html = render_hashtag_box_html(final_20_tags) if otype != "paper" else (
        f"<div style='margin-top:20px;padding:12px 16px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;font-size:13px;color:#334155'>"
        f"<strong>Keywords / 해시태그:</strong> {' '.join(html.escape(t) for t in final_20_tags[:10])}</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{html.escape(topic_ko)} · 블로그용 단일 HTML</title>
<style>
  body {{ margin:0; padding:0; background:#f8fafc; color:#1e293b; font-family:'Pretendard','Noto Sans KR','Malgun Gothic',sans-serif; }}
  .copy-toolbar {{
    position:sticky; top:0; z-index:50; background:#063b2c; color:#fff;
    padding:10px 18px; display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
    border-bottom:3px solid #eab308; box-shadow:0 4px 12px rgba(0,0,0,.15);
  }}
  .copy-toolbar button {{
    background:#03C75A; color:#fff; border:none; border-radius:8px; padding:8px 16px;
    font-weight:800; font-size:13.5px; cursor:pointer;
  }}
  .copy-toolbar button:hover {{ background:#02a94c; }}
  .blog-wrap {{ max-width:820px; margin:24px auto 60px; background:#ffffff; padding:32px 34px; border-radius:14px; box-shadow:0 4px 20px rgba(15,23,42,.06); }}
  .cite-tag {{ display:inline-block; font-size:11.5px; font-weight:700; color:#065f46; background:#ecfdf5; border:1px solid #a7f3d0; border-radius:4px; padding:0 4px; }}
  img {{ max-width:100%; height:auto; border-radius:8px; }}
  {figure_css("web")}
</style>
</head>
<body>
  <div class="copy-toolbar">
    <div>
      <strong>🟢 블로그용 단일 통합 HTML</strong>
      <span style="font-size:12px;color:#a7f3d0;margin-left:8px">[{html.escape(otype_name)}] {html.escape(topic_ko)} (총 {len(chapters)}개 구성 통합)</span>
    </div>
    <div>
      <button onclick="copyBlogBody()">📋 네이버 블로그 본문 전체 복사</button>
    </div>
  </div>

  <div class="blog-wrap" id="blogCopyRoot">
    <div style="background:linear-gradient(135deg,#063b2c,#0f291e);color:#ffffff;padding:24px 26px;border-radius:12px;border-bottom:4px solid #eab308;margin-bottom:24px">
      <div style="font-size:12px;color:#34d399;font-weight:700;letter-spacing:.8px">참참살이 영농 AI 출판도우미 · {html.escape(otype_name)}</div>
      <h1 style="margin:8px 0 4px;font-size:24px;line-height:1.35;color:#ffffff">{html.escape(topic_ko)}</h1>
      {f'<div style="font-size:13.5px;color:#fef08a">{html.escape(topic_en)}</div>' if topic_en else ''}
    </div>

    <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-left:4px solid #03C75A;border-radius:8px;padding:14px 18px;margin-bottom:24px">
      <div style="font-size:14px;font-weight:800;color:#065f46;margin-bottom:6px">📑 한눈에 보는 전체 목차</div>
      <ol style="margin:0;padding-left:20px;font-size:13.5px;line-height:1.7">{''.join(toc_links)}</ol>
    </div>

    {''.join(article_sections)}

    {tag_box_html}
  </div>

  <script>
    async function copyBlogBody() {{
      const root = document.getElementById('blogCopyRoot');
      try {{
        const blob = new Blob([root.innerHTML], {{ type: 'text/html' }});
        const textBlob = new Blob([root.innerText], {{ type: 'text/plain' }});
        await navigator.clipboard.write([new ClipboardItem({{ 'text/html': blob, 'text/plain': textBlob }})]);
        alert('✅ 네이버 블로그용 본문 전체를 복사했습니다! 스마트에디터 ONE에 Ctrl+V로 붙여넣으세요.');
      }} catch (e) {{
        const range = document.createRange();
        range.selectNodeContents(root);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        document.execCommand('copy');
        sel.removeAllRanges();
        alert('✅ 본문이 클립보드에 복사되었습니다! (Ctrl+V)');
      }}
    }}
  </script>
</body>
</html>"""


def _recommended_default_pdf_mode(state: dict[str, Any]) -> tuple[str, str]:
    """1차 산출물 유형에 따른 기본 마스터 PDF 규격 키와 한글 라벨을 반환한다."""
    otype = str(state.get("primary_output_type") or (state.get("output_profile") or {}).get("primary_output_type") or "textbook")
    if otype == "paper":
        return "korean_journal", KOREAN_JOURNAL_PDF_SPEC["label_ko"]
    trim = str((state.get("output_profile") or {}).get("recommended_trim") or "")
    if trim in {"shinkuk", "b5", "a4"}:
        from agro_framework import MULTI_TRIM_SPECS

        return trim, MULTI_TRIM_SPECS[trim]["label_ko"]
    default_map = {
        "textbook": ("b5", "B5 대학교재 (182 × 257 mm)"),
        "storybook": ("shinkuk", "신국판 단행본 (152 × 225 mm)"),
        "report": ("a4", "A4 연구·정책 보고서 (210 × 297 mm)"),
        "lecture": ("a4", "A4 강의 교재 (210 × 297 mm)"),
        "web_publish": ("a4", "A4 웹 출판 인쇄본 (210 × 297 mm)"),
    }
    return default_map.get(otype, ("b5", "B5 대학교재 (182 × 257 mm)"))


def publish_default_outputs(
    project_id: str,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """중복 산출물 없이 기본 핵심 2종(① 마스터 PDF 1종 + ② 블로그용 단일 HTML 1종)만 생성한다."""
    from build_outputs import _render_html_to_pdf
    from figure_registry import load_chapter_visuals
    from subagent_orchestrator import load_project_state, save_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    chapters = _load_project_chapters(ws)
    if not chapters:
        raise FileNotFoundError("출판할 단원 원고(.mdx)가 없습니다. 4단계 집필을 먼저 완료하세요.")

    exp_root = ws / "exports"
    exp_root.mkdir(parents=True, exist_ok=True)
    e_proj_exp = cfg.project_e_exports_dir(project_id)
    e_proj_exp.mkdir(parents=True, exist_ok=True)

    visuals_map = load_chapter_visuals(project_ws=ws)
    bound_visuals_by_ch = {ch["chapter_id"]: len(visuals_map.get(ch["chapter_id"], [])) for ch in chapters}
    total_vis_loaded = sum(bound_visuals_by_ch.values())

    # 1) 마스터 PDF 1종 생성 (paper 모드는 국내 학회지 논문 규격 PDF 자동 적용)
    pdf_mode, pdf_label = _recommended_default_pdf_mode(st)
    if pdf_mode == "korean_journal":
        print_html = render_korean_journal_html(st, chapters, visuals_map=visuals_map)
    else:
        print_html = render_standard_master_html(st, chapters, visuals_map=visuals_map, trim_key=pdf_mode)

    pdf_name = f"{project_id}_master.pdf"
    pdf_path = exp_root / pdf_name
    pdf_ok = _render_html_to_pdf(print_html, pdf_path)
    if pdf_ok and pdf_path.is_file():
        try:
            shutil.copy2(pdf_path, e_proj_exp / pdf_name)
        except Exception:
            pass

    # 2) 블로그용 단일 HTML 1종 생성
    blog_name = f"{project_id}_blog_single.html"
    blog_path = exp_root / blog_name
    blog_html = render_single_blog_html(st, chapters, visuals_map=visuals_map)
    blog_path.write_text(blog_html, encoding="utf-8")
    try:
        shutil.copy2(blog_path, e_proj_exp / blog_name)
    except Exception:
        pass

    rel_pdf = f"/project-files/{project_id}/exports/{pdf_name}" if pdf_ok else ""
    rel_blog = f"/project-files/{project_id}/exports/{blog_name}"

    outputs = dict(st.get("outputs") or {})
    outputs["master_pdf"] = rel_pdf
    outputs["master_pdf_mode"] = pdf_mode
    outputs["master_pdf_label"] = pdf_label
    outputs["blog_single_html"] = rel_blog

    st["outputs"] = outputs
    st["bound_visuals_by_chapter"] = bound_visuals_by_ch
    st.setdefault("checkpoint", {})["published_chapters"] = [ch["chapter_id"] for ch in chapters]
    save_project_state(st, cfg)

    built_files = [str(p) for p in (pdf_path, blog_path) if p.is_file()]
    return {
        "status": "OK",
        "project_id": project_id,
        "chapters_count": len(chapters),
        "total_visuals_bound": total_vis_loaded,
        "default_outputs": {
            "master_pdf": {
                "ok": pdf_ok,
                "mode": pdf_mode,
                "label_ko": pdf_label,
                "url": rel_pdf,
                "path": str(pdf_path) if pdf_ok else "",
                "size_kb": round(pdf_path.stat().st_size / 1024, 1) if pdf_path.is_file() else 0,
            },
            "blog_single_html": {
                "ok": blog_path.is_file(),
                "label_ko": "블로그용 단일 통합 HTML (네이버 스마트에디터 ONE 최적화)",
                "url": rel_blog,
                "path": str(blog_path),
                "size_kb": round(blog_path.stat().st_size / 1024, 1) if blog_path.is_file() else 0,
            },
        },
        "built_files": built_files,
        "generated_at": utc_now_iso(),
    }


def convert_project_output(
    project_id: str,
    target_format: str,
    cfg: PlatformConfig | None = None,
) -> dict[str, Any]:
    """필요 시 사후 포맷 변환 모듈: 요청한 단일 포맷만 온디맨드로 변환 생성한다."""
    from build_outputs import _build_report_docx, _render_html_to_pdf
    from figure_registry import load_chapter_visuals
    from subagent_orchestrator import append_event, load_project_state, save_project_state

    fmt = (target_format or "").strip().lower()
    if fmt not in CONVERSION_FORMATS:
        raise ValueError(f"지원하지 않는 변환 포맷입니다: {target_format} (지원: {', '.join(CONVERSION_FORMATS.keys())})")

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    ws = Path(st["workspace_dir"])
    chapters = _load_project_chapters(ws)
    if not chapters and fmt != "cover_toc":
        raise FileNotFoundError("변환할 단원 원고(.mdx)가 없습니다. 4단계 집필을 먼저 완료하세요.")

    conv_dir = ws / "exports" / "converted"
    conv_dir.mkdir(parents=True, exist_ok=True)
    e_conv_dir = cfg.project_e_exports_dir(project_id) / "converted"
    e_conv_dir.mkdir(parents=True, exist_ok=True)

    visuals_map = load_chapter_visuals(project_ws=ws)
    topic_ko = str(st.get("topic_ko") or project_id).strip()
    topic_en = str(st.get("topic_en") or "").strip()

    spec = CONVERSION_FORMATS[fmt]
    out_url = ""
    out_files: list[str] = []
    size_kb = 0.0
    extra_note = ""

    if fmt == "korean_journal_pdf":
        out_p = conv_dir / f"{project_id}_korean_journal.pdf"
        j_html = render_korean_journal_html(st, chapters, visuals_map=visuals_map)
        ok = _render_html_to_pdf(j_html, out_p)
        if not ok:
            raise RuntimeError("국내 학회지 규격 PDF 렌더링 실패 (Headless Chrome/Edge 확인 필요)")
        shutil.copy2(out_p, e_conv_dir / out_p.name)
        out_url = f"/project-files/{project_id}/exports/converted/{out_p.name}"
        out_files = [str(out_p)]
        size_kb = round(out_p.stat().st_size / 1024, 1)
        extra_note = KOREAN_JOURNAL_PDF_SPEC["label_ko"]

    elif fmt in {"b5_pdf", "shinkuk_pdf", "a4_pdf"}:
        trim_key = fmt.replace("_pdf", "")
        out_p = conv_dir / f"{project_id}_{trim_key}.pdf"
        m_html = render_standard_master_html(st, chapters, visuals_map=visuals_map, trim_key=trim_key)
        ok = _render_html_to_pdf(m_html, out_p)
        if not ok:
            raise RuntimeError(f"{trim_key.upper()} PDF 렌더링 실패")
        shutil.copy2(out_p, e_conv_dir / out_p.name)
        out_url = f"/project-files/{project_id}/exports/converted/{out_p.name}"
        out_files = [str(out_p)]
        size_kb = round(out_p.stat().st_size / 1024, 1)

    elif fmt == "docx":
        out_p = conv_dir / f"{project_id}_master.docx"
        combined_md = "\n\n---\n\n".join(ch["body"] for ch in chapters)
        _build_report_docx(
            f"{project_id}_master",
            topic_ko,
            f"{topic_en} · 참참살이 영농 AI 출판도우미 합본",
            combined_md,
            out_p,
            visuals_map=visuals_map,
        )
        if out_p.is_file():
            shutil.copy2(out_p, e_conv_dir / out_p.name)
            out_url = f"/project-files/{project_id}/exports/converted/{out_p.name}"
            out_files = [str(out_p)]
            size_kb = round(out_p.stat().st_size / 1024, 1)

    elif fmt == "markdown_master":
        out_p = conv_dir / f"{project_id}_master.md"
        header = f"# {topic_ko}\n\n" + (f"*{topic_en}*\n\n" if topic_en else "")
        out_p.write_text(header + "\n\n---\n\n".join(ch["body"] for ch in chapters) + "\n", encoding="utf-8")
        shutil.copy2(out_p, e_conv_dir / out_p.name)
        out_url = f"/project-files/{project_id}/exports/converted/{out_p.name}"
        out_files = [str(out_p)]
        size_kb = round(out_p.stat().st_size / 1024, 1)

    elif fmt == "chapter_split_html":
        split_dir = conv_dir / "chapters_html"
        split_dir.mkdir(parents=True, exist_ok=True)
        e_split = e_conv_dir / "chapters_html"
        e_split.mkdir(parents=True, exist_ok=True)
        links: list[str] = []
        for ch in chapters:
            cid = ch["chapter_id"]
            sub_html = render_single_blog_html(
                {**st, "topic_ko": f"{topic_ko} — {ch['title']}"},
                [ch],
                visuals_map=visuals_map,
            )
            fp = split_dir / f"{cid}_blog.html"
            fp.write_text(sub_html, encoding="utf-8")
            shutil.copy2(fp, e_split / fp.name)
            out_files.append(str(fp))
            links.append(f"<li><a href='{fp.name}' target='_blank'>{html.escape(cid)} · {html.escape(ch['title'])}</a></li>")
        idx_p = split_dir / "index.html"
        idx_p.write_text(
            f"<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'><title>{html.escape(topic_ko)} 단원별 블로그 HTML</title>"
            "<style>body{font-family:'Pretendard','Malgun Gothic',sans-serif;max-width:760px;margin:28px auto;padding:0 16px;line-height:1.8}a{color:#065f46;font-weight:700}</style></head>"
            f"<body><h2>🌐 {html.escape(topic_ko)} — 단원별 분할 블로그 HTML ({len(chapters)}개)</h2><ol>{''.join(links)}</ol></body></html>",
            encoding="utf-8",
        )
        shutil.copy2(idx_p, e_split / idx_p.name)
        out_url = f"/project-files/{project_id}/exports/converted/chapters_html/index.html"
        size_kb = round(sum(Path(p).stat().st_size for p in out_files if Path(p).is_file()) / 1024, 1)
        extra_note = f"{len(chapters)}개 단원 분할 생성"

    elif fmt == "quarto_book":
        q_dir = conv_dir / "quarto"
        q_dir.mkdir(parents=True, exist_ok=True)
        qmd_list: list[str] = []
        for ch in chapters:
            qname = f"{ch['chapter_id']}.qmd"
            qp = q_dir / qname
            qp.write_text(f"---\ntitle: \"{ch['title']}\"\n---\n\n{ch['body']}\n", encoding="utf-8")
            out_files.append(str(qp))
            qmd_list.append(qname)
        q_cfg = {
            "project": {"type": "book", "output-dir": "_book"},
            "book": {
                "title": topic_ko,
                "subtitle": topic_en,
                "author": "참참살이 영농 AI 출판도우미",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "chapters": qmd_list,
            },
            "format": {"pdf": {"documentclass": "scrbook", "papersize": "b5", "toc": True}, "docx": {"toc": True}},
        }
        qy = q_dir / "_quarto.yml"
        qy.write_text(yaml.safe_dump(q_cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        out_files.insert(0, str(qy))
        out_url = f"/project-files/{project_id}/exports/converted/quarto/_quarto.yml"
        size_kb = round(sum(Path(p).stat().st_size for p in out_files if Path(p).is_file()) / 1024, 1)
        extra_note = f"_quarto.yml + {len(qmd_list)}개 .qmd"

    elif fmt == "cover_toc":
        from build_cover_toc import build_project_cover_and_toc

        fm_res = build_project_cover_and_toc(project_id, cfg=cfg)
        files_dict = fm_res.get("files") or {}
        out_url = files_dict.get("html") or files_dict.get("pdf") or ""
        out_files = [str(Path(fm_res["local_dir"]) / f"cover_and_toc.{ext}") for ext in ("html", "pdf", "docx", "md") if (Path(fm_res["local_dir"]) / f"cover_and_toc.{ext}").is_file()]
        size_kb = round(sum(Path(p).stat().st_size for p in out_files if Path(p).is_file()) / 1024, 1)
        extra_note = f"표지·머리말·목차 ({fm_res.get('chapter_count', 0)}장)"

    record = {
        "format": fmt,
        "icon": spec["icon"],
        "name_ko": spec["name_ko"],
        "url": out_url,
        "size_kb": size_kb,
        "files_count": len(out_files),
        "note": extra_note,
        "converted_at": utc_now_iso(),
    }
    conv_map = dict(st.get("converted_outputs") or {})
    conv_map[fmt] = record
    st["converted_outputs"] = conv_map
    outputs = dict(st.get("outputs") or {})
    if out_url:
        outputs[f"converted_{fmt}"] = out_url
    st["outputs"] = outputs
    save_project_state(st, cfg)
    append_event(
        project_id,
        "output-converter",
        "stage6_publish_report",
        f"사후 포맷 변환 완료 [{spec['icon']} {spec['name_ko']}] ({size_kb} KB)",
        cfg=cfg,
    )
    return {
        "status": "OK",
        "project_id": project_id,
        "conversion": record,
        "converted_outputs": conv_map,
    }


def list_project_outputs_summary(project_id: str, cfg: PlatformConfig | None = None) -> dict[str, Any]:
    """프로젝트의 기본 2종 산출물과 사후 변환된 산출물 목록을 정리해 반환한다."""
    from subagent_orchestrator import load_project_state

    cfg = cfg or get_config()
    st = load_project_state(project_id, cfg)
    if not st:
        raise FileNotFoundError(f"Project not found: {project_id}")

    outputs = st.get("outputs") or {}
    pdf_mode, pdf_label = _recommended_default_pdf_mode(st)
    return {
        "project_id": project_id,
        "primary_output_type": st.get("primary_output_type") or "textbook",
        "default_outputs": {
            "master_pdf": outputs.get("master_pdf") or "",
            "master_pdf_mode": outputs.get("master_pdf_mode") or pdf_mode,
            "master_pdf_label": outputs.get("master_pdf_label") or pdf_label,
            "blog_single_html": outputs.get("blog_single_html") or "",
        },
        "converted_outputs": st.get("converted_outputs") or {},
        "available_formats": CONVERSION_FORMATS,
        "korean_journal_spec": KOREAN_JOURNAL_PDF_SPEC,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="기본 2종 출판기(PDF + 블로그용 단일 HTML) 및 사후 포맷 변환 모듈")
    parser.add_argument("--project", required=True, help="프로젝트 ID")
    parser.add_argument("--default-only", action="store_true", help="기본 2종 산출물(PDF + 블로그용 단일 HTML)만 생성")
    parser.add_argument("--format", default="", choices=[""] + list(CONVERSION_FORMATS.keys()), help="사후 변환할 대상 포맷")
    args = parser.parse_args()

    if args.format:
        res = convert_project_output(args.project, args.format)
    else:
        res = publish_default_outputs(args.project)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
