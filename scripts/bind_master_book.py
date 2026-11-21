"""16개 단원을 출판 인쇄 판형(신국판 / B5 대학교재 / A4) 합본 PDF 및 Word DOCX로 자동 제본하는 스크립트.

지원 인쇄 판형 (--format):
1. shinkuk (신국판, 152mm × 225mm): 국내 전문 학술 단행본 표준 판형 (약 420~520p 규모)
2. b5      (B5 4·6배판, 182mm × 257mm): 국내 이공계·농학 대학교재 표준 판형
3. a4      (A4, 210mm × 297mm): 기관 보고서·대형 출력 마스터 판형
4. all     (기본값): 위 3종 판형 PDF + 20종 도해·차트가 내장된 Word DOCX 동시 제본

포함 구성:
1. 표지 (Cover Page) — 도서명, 영문제목, 대상 독자, 5부 16개 단원 개요, 판형 규격, 발행일
2. 머리말 및 교재 활용 가이드 (Preface)
3. 전체 목차 (Table of Contents — 5부, 16개 장, 모든 절 헤딩)
4. 그림·도표 목차 (List of Figures — 나노바나나 AI 과학 도해 4종 + 정량 SVG 차트 16종)
5. 제1부 ~ 제5부 간지(Part Divider) + 제1장 ~ 제16장 본문 전체(각 장 도해·차트 자동 삽입)
6. 통합 참고문헌 목록 (Unified Consolidated Bibliography — 중복 제거 SRC-01 ~ SRC-NN)
7. 가나다·알파벳 순 핵심 용어 색인 (Subject Index — 용어별 수록 단원 매핑)

출력 경로:
- content/exports/master_book/Soil_Organic_Matter_Master_Book_Shinkuk.pdf  (신국판)
- content/exports/master_book/Soil_Organic_Matter_Master_Book_B5.pdf       (B5 대학교재)
- content/exports/master_book/Soil_Organic_Matter_Master_Book.pdf          (A4 마스터)
- content/exports/master_book/Soil_Organic_Matter_Master_Book.docx         (Word 합본, 20종 도해 삽입)
- E:\\SMC_Report_Platform_Data\\exports\\master_book\\ (동일 미러 저장)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader

from build_outputs import (
    MD_PARSER,
    _clean_mdx_artifacts,
    _highlight_citations_html,
    _load_all_sources_map,
    _parse_frontmatter,
    _render_html_to_pdf,
    strip_exercise_sections,
)
from config import PlatformConfig, get_config
from figure_registry import figure_css, inject_figures_into_chapter_html, load_chapter_visuals
from math_typography import add_rich_runs_to_docx_paragraph, math_typography_css


TRIM_PRESETS: dict[str, dict[str, Any]] = {
    "shinkuk": {
        "label_ko": "신국판 단행본 (152 × 225 mm)",
        "filename": "Soil_Organic_Matter_Master_Book_Shinkuk.pdf",
        "html_filename": "Soil_Organic_Matter_Master_Book_Shinkuk.html",
        "page_size": "152mm 225mm",
        "margin": "18mm 15mm 20mm 17mm",
        "body_pt": "9.3pt",
        "line_height": "1.66",
        "h1_pt": "14.5pt",
        "h2_pt": "11.5pt",
        "h3_pt": "10pt",
        "table_pt": "7.8pt",
        "cover_height": "180mm",
        "cover_title_pt": "20pt",
        "part_height": "175mm",
        "part_title_pt": "17pt",
        "fig_max_h": "86mm",
        "idx_cols": 2,
    },
    "b5": {
        "label_ko": "B5 대학교재 (182 × 257 mm)",
        "filename": "Soil_Organic_Matter_Master_Book_B5.pdf",
        "html_filename": "Soil_Organic_Matter_Master_Book_B5.html",
        "page_size": "182mm 257mm",
        "margin": "20mm 17mm 20mm 19mm",
        "body_pt": "9.8pt",
        "line_height": "1.70",
        "h1_pt": "15.5pt",
        "h2_pt": "12.5pt",
        "h3_pt": "10.6pt",
        "table_pt": "8.3pt",
        "cover_height": "210mm",
        "cover_title_pt": "23pt",
        "part_height": "205mm",
        "part_title_pt": "19pt",
        "fig_max_h": "102mm",
        "idx_cols": 2,
    },
    "a4": {
        "label_ko": "A4 마스터판 (210 × 297 mm)",
        "filename": "Soil_Organic_Matter_Master_Book.pdf",
        "html_filename": "Soil_Organic_Matter_Master_Book.html",
        "page_size": "210mm 297mm",
        "margin": "20mm 18mm 20mm 18mm",
        "body_pt": "10.2pt",
        "line_height": "1.72",
        "h1_pt": "16pt",
        "h2_pt": "13pt",
        "h3_pt": "11pt",
        "table_pt": "8.8pt",
        "cover_height": "245mm",
        "cover_title_pt": "26pt",
        "part_height": "235mm",
        "part_title_pt": "21pt",
        "fig_max_h": "118mm",
        "idx_cols": 2,
    },
}


def _extract_glossary_terms(ch_id: str, body: str) -> list[tuple[str, str, str]]:
    """각 단원의 핵심 용어집 표에서 (국문용어, 영문용어, ch_id) 목록을 추출한다."""
    m = re.search(r"(?m)^##\s*핵심 용어집[\s\S]*?(?=^##\s|\Z)", body)
    if not m:
        return []
    terms: list[tuple[str, str, str]] = []
    for ln in m.group(0).splitlines():
        s = ln.strip()
        if not s.startswith("|") or ":---" in s or "용어" in s[:15]:
            continue
        cells = [re.sub(r"\*\*|`", "", c).strip() for c in s.strip("|").split("|")]
        if len(cells) >= 2 and cells[0]:
            terms.append((cells[0], cells[1], ch_id))
    return terms


def _strip_chapter_references(body: str) -> str:
    """합본에서는 개별 단원 말미의 참고문헌 표를 통합 참고문헌으로 일원화한다."""
    return re.split(r"(?m)^##\s*참고문헌", body, maxsplit=1)[0].strip()


def _book_trim_css(preset: dict[str, Any], header_label: str) -> str:
    accent = "#1d4ed8"
    return f"""
    @page {{
      size: {preset['page_size']};
      margin: {preset['margin']};
      @top-right {{ content: "{header_label}"; font-size: 7.8pt; color: #64748b; }}
      @bottom-center {{ content: "— " counter(page) " —"; font-size: 8.5pt; color: #475569; }}
    }}
    @page :first {{
      @top-right {{ content: none; }}
      @bottom-center {{ content: none; }}
    }}
    body {{
      font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
      font-size: {preset['body_pt']};
      line-height: {preset['line_height']};
      color: #1e293b;
      margin: 0;
      text-align: justify;
    }}
    h1 {{ font-size: {preset['h1_pt']}; color: #0f172a; border-bottom: 2px solid {accent}; padding-bottom: 5px; margin-top: 18px; text-align: left; page-break-after: avoid; }}
    h2 {{ font-size: {preset['h2_pt']}; color: {accent}; border-left: 4px solid {accent}; padding-left: 9px; margin-top: 18px; text-align: left; page-break-after: avoid; }}
    h3 {{ font-size: {preset['h3_pt']}; color: #0f172a; margin-top: 12px; text-align: left; page-break-after: avoid; }}
    h4 {{ font-size: 9.2pt; color: #047857; background: #ecfdf5; border-left: 3.5px solid #059669; padding: 4px 9px; margin: 8px 0 5px; border-radius: 0 5px 5px 0; text-align: left; page-break-after: avoid; }}
    blockquote, .callout {{
      background: #f8fafc;
      border-left: 4px solid {accent};
      padding: 8px 12px;
      margin: 10px 0;
      border-radius: 0 6px 6px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0 14px;
      font-size: {preset['table_pt']};
      page-break-inside: auto;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 5px 7px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{ background: {accent}; color: #ffffff; font-weight: 700; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    code {{
      background: #f1f5f9;
      padding: 1px 4px;
      border-radius: 3px;
      font-family: Consolas, 'D2Coding', monospace;
      font-size: 8.2pt;
    }}
    pre {{
      background: #0f172a;
      color: #e2e8f0;
      padding: 8px 10px;
      border-radius: 6px;
      overflow-x: auto;
      font-size: 7.8pt;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    pre code {{ background: transparent; color: inherit; padding: 0; }}
    .cite-tag {{
      display: inline-block;
      font-size: 7.5pt;
      font-weight: 700;
      color: {accent};
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 3px;
      padding: 0 3px;
    }}
    .page-break {{ page-break-before: always; }}
    .book-cover {{
      height: {preset['cover_height']};
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 18mm 14mm;
      box-sizing: border-box;
      background: linear-gradient(155deg, #0f172a 0%, #1e3a8a 60%, #0369a1 100%);
      color: #ffffff;
      border-radius: 10px;
      text-align: left;
    }}
    .cover-top {{ font-size: 8.8pt; letter-spacing: 1.2px; color: #7dd3fc; font-weight: 700; margin-bottom: 14px; }}
    .cover-title {{ font-size: {preset['cover_title_pt']}; line-height: 1.3; color: #ffffff; border: none; margin: 0 0 10px; padding: 0; }}
    .cover-en {{ font-size: 10.5pt; color: #cbd5e1; margin-bottom: 18px; }}
    .cover-rule {{ width: 80px; height: 4px; background: #38bdf8; margin-bottom: 18px; }}
    .cover-meta {{ font-size: 9pt; line-height: 1.85; color: #e2e8f0; }}
    .part-divider {{
      height: {preset['part_height']};
      display: flex;
      flex-direction: column;
      justify-content: center;
      padding: 18mm 14mm;
      box-sizing: border-box;
      background: #f8fafc;
      border-left: 8px solid #1d4ed8;
      text-align: left;
    }}
    .part-kicker {{ font-size: 10.5pt; font-weight: 700; color: #1d4ed8; letter-spacing: 2px; margin-bottom: 8px; }}
    .part-title {{ font-size: {preset['part_title_pt']}; color: #0f172a; border: none; margin: 0 0 18px; padding: 0; }}
    .part-chapters {{ font-size: 9.8pt; line-height: 1.9; color: #334155; }}
    .toc-part {{ font-size: 10pt; font-weight: 700; color: #1d4ed8; margin-top: 10px; border-bottom: 1px solid #cbd5e1; padding-bottom: 2px; }}
    .toc-ch {{ font-size: 9pt; margin: 4px 0 2px 8px; color: #0f172a; }}
    .toc-sec {{ font-size: 8pt; margin: 1px 0 1px 18px; color: #475569; }}
    .lof-item {{ font-size: 8.5pt; padding: 3px 0; border-bottom: 1px dotted #cbd5e1; }}
    .idx-grid {{ column-count: {preset['idx_cols']}; column-gap: 16px; font-size: 8.2pt; }}
    .idx-item {{ break-inside: avoid; padding: 2px 0; border-bottom: 1px dotted #cbd5e1; display: flex; justify-content: space-between; gap: 6px; }}
    .idx-item span {{ color: #1d4ed8; font-weight: 600; white-space: nowrap; }}
    {figure_css("print")}
    {math_typography_css("print")}
    .book-figure .fig-img {{ max-height: {preset['fig_max_h']}; }}
    """


def _build_master_docx(
    book_meta: dict[str, Any],
    parts_data: list[dict[str, Any]],
    chapters_content: dict[str, tuple[dict[str, Any], str]],
    cited_sources: list[dict[str, Any]],
    index_map: dict[str, list[str]],
    visuals_map: dict[str, list[dict[str, Any]]],
    docx_path: Path,
) -> int:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Malgun Gothic"
    normal.font.size = Pt(10.0)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

    def _font(run, size: float | None = None, bold: bool | None = None, color: tuple[int, int, int] | None = None):
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
        if size is not None:
            run.font.size = Pt(size)
        if bold is not None:
            run.bold = bold
        if color is not None:
            run.font.color.rgb = RGBColor(*color)

    embedded_figures = 0

    # 1. Cover Page
    for _ in range(4):
        doc.add_paragraph()
    p_k = doc.add_paragraph()
    p_k.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p_k.add_run("STANDARD ADVANCED TEXTBOOK · 전문 분야 대학교재 합본"), 11, True, (29, 78, 216))

    p_t = doc.add_paragraph()
    p_t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p_t.add_run(book_meta.get("title_ko", "토양 유기물학")), 24, True, (15, 23, 42))

    p_en = doc.add_paragraph()
    p_en.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(p_en.add_run(book_meta.get("title_en", "")), 12, False, (71, 85, 105))

    total_figs = sum(len(v) for v in visuals_map.values())
    doc.add_paragraph()
    p_meta = doc.add_paragraph()
    p_meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(
        p_meta.add_run(
            f"대상 독자: {book_meta.get('target_audience', '')}\n"
            f"구성: 총 {len(parts_data)}부 {len(chapters_content)}개 단원 · 검증 1차 출처 {len(cited_sources)}건 · 과학 도해·정량 차트 {total_figs}종 수록\n"
            f"편찬일: {datetime.now().strftime('%Y-%m-%d')}"
        ),
        10,
        False,
        (51, 65, 85),
    )
    doc.add_page_break()

    # 2. Full Table of Contents
    h_toc = doc.add_heading("전체 목차 (Table of Contents)", level=1)
    for r in h_toc.runs:
        _font(r, 16, True, (29, 78, 216))
    for part in parts_data:
        pp = doc.add_paragraph()
        _font(pp.add_run(f"{part['title']} ({part['pages']}p 설계)"), 11.5, True, (15, 23, 42))
        for ch in part.get("chapters", []):
            cid = ch["chapter_id"]
            cp = doc.add_paragraph(style="List Bullet")
            _font(cp.add_run(f"{ch['title']} [{cid}]"), 10, False, (30, 41, 59))
    doc.add_page_break()

    # 2b. List of Figures
    h_lof = doc.add_heading("그림 및 정량 차트 목차 (List of Figures)", level=1)
    for r in h_lof.runs:
        _font(r, 15, True, (29, 78, 216))
    for cid in sorted(visuals_map.keys()):
        for v in visuals_map[cid]:
            p = doc.add_paragraph(style="List Bullet")
            tag = "[Nano Banana 과학 도해] " if v["kind"] == "nano_banana" else "[정량 SVG 차트] "
            _font(p.add_run(f"{tag}{v['caption_ko']}"), 9.2, False, (30, 41, 59))
    doc.add_page_break()

    def _add_md_table(table_lines: list[str]) -> None:
        parsed_rows = []
        for tl in table_lines:
            cells = [c.strip() for c in tl.strip().strip("|").split("|")]
            if all(re.match(r"^:?-{2,}:?$", c.replace(" ", "")) for c in cells if c):
                continue
            parsed_rows.append(cells)
        if not parsed_rows:
            return
        ncols = max(len(r) for r in parsed_rows)
        tbl = doc.add_table(rows=len(parsed_rows), cols=ncols)
        tbl.style = "Table Grid"
        for r_idx, row in enumerate(parsed_rows):
            for c_idx in range(ncols):
                val = row[c_idx] if c_idx < len(row) else ""
                cell = tbl.cell(r_idx, c_idx)
                cell.text = ""
                add_rich_runs_to_docx_paragraph(
                    cell.paragraphs[0],
                    val,
                    font_size=8.2,
                    color_rgb=(255, 255, 255) if r_idx == 0 else None,
                    base_bold=(r_idx == 0),
                )
                if r_idx == 0:
                    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="1E3A8A"/>'))

    def _add_docx_figure(vis: dict[str, Any]) -> bool:
        img_str = vis.get("docx_image_path", "")
        if not img_str or not Path(img_str).is_file():
            return False
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.add_run().add_picture(img_str, width=Inches(5.5))
        fig_no = vis.get("fig_no", "")
        title_ko = vis.get("title_ko") or vis.get("caption_ko", "")
        header_line = f"[{fig_no}] {title_ko}" if fig_no else title_ko
        p_cap = doc.add_paragraph()
        _font(p_cap.add_run(header_line), 9.0, True, (15, 23, 42))
        desc_ko = vis.get("description_ko", "")
        if desc_ko:
            p_desc = doc.add_paragraph()
            _font(p_desc.add_run(desc_ko), 8.8, False, (51, 65, 85))
        return True

    # 3. Parts & 16 Chapters
    for part in parts_data:
        h_part = doc.add_heading(part["title"], level=0)
        for r in h_part.runs:
            _font(r, 18, True, (29, 78, 216))
        doc.add_page_break()

        for ch in part.get("chapters", []):
            cid = ch["chapter_id"]
            if cid not in chapters_content:
                continue
            _, body = chapters_content[cid]
            clean_body = _clean_mdx_artifacts(_strip_chapter_references(body))
            ch_visuals = list(visuals_map.get(cid, []))
            vis_idx = 0
            h2_seen = 0

            lines = clean_body.splitlines()
            i = 0
            while i < len(lines):
                ln = lines[i].strip()
                if not ln:
                    i += 1
                    continue
                if ln.startswith("|") and "|" in ln[1:]:
                    tbl_block = []
                    while i < len(lines) and lines[i].strip().startswith("|"):
                        tbl_block.append(lines[i].strip())
                        i += 1
                    _add_md_table(tbl_block)
                    continue
                if ln.startswith("<a id="):
                    i += 1
                    continue
                if ln.startswith("# "):
                    hh = doc.add_heading("", level=1)
                    add_rich_runs_to_docx_paragraph(hh, ln[2:].strip(), font_size=15, base_bold=True, color_rgb=(15, 23, 42))
                elif ln.startswith("## "):
                    hh = doc.add_heading("", level=2)
                    add_rich_runs_to_docx_paragraph(hh, ln[3:].strip(), font_size=12.5, base_bold=True, color_rgb=(29, 78, 216))
                    h2_seen += 1
                    # 1번째, 2번째 절 직후 해당 단원 도해/차트 삽입
                    if vis_idx < len(ch_visuals) and h2_seen in (1, 2):
                        if _add_docx_figure(ch_visuals[vis_idx]):
                            embedded_figures += 1
                        vis_idx += 1
                elif ln.startswith("### "):
                    hh = doc.add_heading("", level=3)
                    add_rich_runs_to_docx_paragraph(hh, ln[4:].strip(), font_size=11, base_bold=True, color_rgb=(30, 41, 59))
                elif ln.startswith("#### "):
                    p_ans = doc.add_paragraph()
                    p_ans._p.get_or_add_pPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="ECFDF5"/>'))
                    add_rich_runs_to_docx_paragraph(p_ans, ln[5:].strip(), font_size=10.2, base_bold=True, color_rgb=(4, 120, 87))
                elif ln.startswith("*[↑ 문제"):
                    i += 1
                    continue
                elif ln.startswith('<div class="math-block">'):
                    p_eq = doc.add_paragraph()
                    p_eq.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p_eq._p.get_or_add_pPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F1F5F9"/>'))
                    add_rich_runs_to_docx_paragraph(p_eq, ln, font_size=9.8, color_rgb=(15, 23, 42))
                elif ln.startswith(("* ", "- ")):
                    p = doc.add_paragraph(style="List Bullet")
                    add_rich_runs_to_docx_paragraph(p, ln[2:].strip(), font_size=9.8)
                else:
                    p = doc.add_paragraph()
                    add_rich_runs_to_docx_paragraph(p, ln.lstrip("> ").strip(), font_size=9.8)
                i += 1

            while vis_idx < len(ch_visuals):
                if _add_docx_figure(ch_visuals[vis_idx]):
                    embedded_figures += 1
                vis_idx += 1
            doc.add_page_break()

    # 4. Unified Bibliography
    h_ref = doc.add_heading("통합 참고문헌 및 검증 출처 총람 (Unified Bibliography)", level=1)
    for r in h_ref.runs:
        _font(r, 15, True, (29, 78, 216))
    for s in cited_sources:
        p = doc.add_paragraph(style="List Bullet")
        _font(
            p.add_run(
                f"[{s.get('source_id')}] {s.get('title', '')} — {s.get('url', '')} ({s.get('license_note', '')})"
            ),
            8.8,
        )
    doc.add_page_break()

    # 5. Subject Index
    h_idx = doc.add_heading("핵심 용어 색인 (Subject Index)", level=1)
    for r in h_idx.runs:
        _font(r, 15, True, (29, 78, 216))
    for term in sorted(index_map.keys()):
        p = doc.add_paragraph()
        _font(p.add_run(f"{term}  ······  {', '.join(sorted(set(index_map[term])))}"), 9.5)

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(docx_path))
    return embedded_figures


def bind_master_book(
    formats: list[str] | None = None,
    build_docx: bool = True,
    cfg: PlatformConfig | None = None,
    include_exercises: bool = True,
) -> dict[str, Any]:
    cfg = cfg or get_config()
    target_formats = formats or ["shinkuk", "b5", "a4"]

    master = yaml.safe_load((cfg.blueprints_dir / "master_outline.yaml").read_text(encoding="utf-8"))
    book_meta = master.get("book_metadata", {})
    parts_data = master.get("parts", [])
    sources_map = _load_all_sources_map(cfg)
    visuals_map = load_chapter_visuals(cfg)

    chapters_content: dict[str, tuple[dict[str, Any], str]] = {}
    all_cited_ids: set[str] = set()
    index_map: dict[str, list[str]] = {}
    toc_rows_html: list[str] = []

    for part in parts_data:
        toc_rows_html.append(f'<div class="toc-part">{html.escape(part["title"])} ({part["pages"]}p 설계)</div>')
        for ch in part.get("chapters", []):
            cid = ch["chapter_id"]
            mdx_p = cfg.chapters_dir / f"{cid}.mdx"
            if not mdx_p.is_file():
                continue
            meta, body = _parse_frontmatter(mdx_p.read_text(encoding="utf-8"))
            if not include_exercises:
                body = strip_exercise_sections(body)
            chapters_content[cid] = (meta, body)
            for sid in re.findall(r"\[(SRC-\d{2,4})", body):
                all_cited_ids.add(sid)
            for ko_t, en_t, c_ref in _extract_glossary_terms(cid, body):
                label = f"{ko_t} ({en_t})" if en_t and en_t.lower() != ko_t.lower() else ko_t
                index_map.setdefault(label, []).append(c_ref.upper())

            toc_rows_html.append(f'<div class="toc-ch"><b>{html.escape(ch["title"])}</b></div>')
            for h2 in re.findall(r"(?m)^##\s+(.+)$", _strip_chapter_references(body)):
                if not any(skip in h2 for skip in ("핵심 용어집", "이해도 점검")):
                    toc_rows_html.append(f'<div class="toc-sec">· {html.escape(h2.strip())}</div>')

    if cfg.glossary_path.is_file():
        g_syn = json.loads(cfg.glossary_path.read_text(encoding="utf-8")).get("synonyms", {})
        for canonical in sorted(set(g_syn.values())):
            hits = [cid.upper() for cid, (_, b) in chapters_content.items() if canonical.split("(")[0] in b]
            if hits:
                index_map.setdefault(canonical, []).extend(hits)

    cited_sources = [
        sources_map[sid]
        for sid in sorted(all_cited_ids, key=lambda x: int(x.split("-")[1]) if "-" in x and x.split("-")[1].isdigit() else 9999)
        if sid in sources_map
    ]

    # List of Figures HTML
    lof_items: list[str] = []
    total_visuals = 0
    for cid in sorted(visuals_map.keys()):
        for v in visuals_map[cid]:
            total_visuals += 1
            badge = "Nano Banana AI" if v["kind"] == "nano_banana" else "SVG 차트"
            lof_items.append(
                f'<div class="lof-item"><b>[{cid.upper()} · {badge}]</b> {html.escape(v["caption_ko"])}</div>'
            )

    # 공통 본문 HTML 조립 (단원별 도해·차트 20종 자동 삽입 포함)
    body_sections: list[str] = []

    # 2. Preface
    body_sections.append(
        f"""
        <section class="page-break">
          <h1>머리말 및 본서의 구성</h1>
          <p>본 합본 교재 <b>《{html.escape(book_meta.get("title_ko", "토양 유기물학"))}》</b>은 전통적 부식화학(Humus Chemistry)에서 현대 토양 연속체 모델(Soil Continuum Model)과 입자성·광물결합 유기물(POM/MAOM) 패러다임, 유기물 질소 동역학 및 탄소 분해 모델링(RothC·CENTURY·DNDC·MIMICS·CORPSE·SoilR)의 이론과 실전, 그리고 한국(농촌진흥청·흙토람·한국토양비료학회)·일본(MAFF·NARO·SSPN)·미국(USDA SARE·Cornell CASH·SSSAJ)·유럽(Rothamsted·EU EEA·EJP SOIL·4 per 1000·EJSS)의 최신 연구와 현장 관리 기준을 한 권에 집대성한 전문 전공서입니다.</p>
          <p>본서의 모든 사실적 주장과 수치, 모델 매개변수에는 <code>[SRC-NN]</code> 출처 인용키가 부착되어 있으며, <b>나노바나나(Nano Banana) 과학 일러스트 4종</b>과 <b>16개 전 단원 정량 SVG 차트·모식도</b> 총 {total_visuals}종의 시각 자료가 본문 흐름에 맞춰 수록되어 있습니다. 말미의 <b>통합 참고문헌 총람</b> 및 <b>핵심 용어 색인</b>을 통해 원천 문헌과 관련 단원을 즉시 역추적할 수 있습니다.</p>
        </section>
        """
    )

    # 3. Complete Table of Contents
    body_sections.append(
        f"""
        <section class="page-break">
          <h1>전체 목차 (Table of Contents)</h1>
          <div class="toc-container">{''.join(toc_rows_html)}</div>
        </section>
        """
    )

    # 4. List of Figures
    body_sections.append(
        f"""
        <section class="page-break">
          <h1>그림 및 정량 차트 목차 (List of Figures)</h1>
          <p>나노바나나(Nano Banana) 과학 도해 4종 및 전 단원 벡터 SVG 정량 차트·모식도 16종(총 {total_visuals}종) 목록입니다.</p>
          <div class="lof-container">{''.join(lof_items)}</div>
        </section>
        """
    )

    # 5. Parts & 16 Chapters (with figures injected)
    for part in parts_data:
        ch_list_html = "".join(f"<li>{html.escape(c['title'])}</li>" for c in part.get("chapters", []))
        body_sections.append(
            f"""
            <section class="part-divider page-break">
              <div class="part-kicker">PART {part['part_number']}</div>
              <h1 class="part-title">{html.escape(part['title'])}</h1>
              <ul class="part-chapters">{ch_list_html}</ul>
            </section>
            """
        )
        for ch in part.get("chapters", []):
            cid = ch["chapter_id"]
            if cid not in chapters_content:
                continue
            _, body = chapters_content[cid]
            ch_body = _clean_mdx_artifacts(_strip_chapter_references(body))
            rendered = _highlight_citations_html(MD_PARSER.render(ch_body))
            rendered = inject_figures_into_chapter_html(cid, rendered, visuals_map, theme="print")
            body_sections.append(f'<article class="chapter-section page-break">{rendered}</article>')

    # 6. Unified Bibliography
    ref_rows = "".join(
        f"<tr><td><b>{html.escape(s.get('source_id',''))}</b></td>"
        f"<td>{html.escape(s.get('source_type',''))}</td>"
        f"<td>{html.escape(s.get('title',''))}</td>"
        f"<td style='word-break:break-all;'>{html.escape(s.get('url',''))}</td>"
        f"<td>{html.escape(s.get('license_note',''))}</td></tr>"
        for s in cited_sources
    )
    body_sections.append(
        f"""
        <section class="page-break">
          <h1>통합 참고문헌 및 검증 출처 총람 (Unified Bibliography)</h1>
          <p>본 합본 교재 전체 {len(chapters_content)}개 단원에서 인용·검증된 총 {len(cited_sources)}건의 1차 출처 목록입니다.</p>
          <table>
            <thead><tr><th style="width:58px;">출처 ID</th><th style="width:52px;">유형</th><th>제목 및 서지 정보</th><th>URL / 경로</th><th>라이선스·접근 상태</th></tr></thead>
            <tbody>{ref_rows}</tbody>
          </table>
        </section>
        """
    )

    # 7. Subject Index
    idx_items = "".join(
        f"<div class='idx-item'><b>{html.escape(term)}</b> <span>{html.escape(', '.join(sorted(set(chs))))}</span></div>"
        for term, chs in sorted(index_map.items())
    )
    body_sections.append(
        f"""
        <section class="page-break">
          <h1>핵심 용어 색인 (Subject Index)</h1>
          <div class="idx-grid">{idx_items}</div>
        </section>
        """
    )

    body_html_joined = "".join(body_sections)

    out_dir = cfg.workspace_exports_dir / "master_book"
    out_dir.mkdir(parents=True, exist_ok=True)
    e_dir = cfg.exports_dir / "master_book"
    e_dir.mkdir(parents=True, exist_ok=True)

    editions_report: dict[str, Any] = {}
    for fmt_key in target_formats:
        if fmt_key not in TRIM_PRESETS:
            continue
        preset = TRIM_PRESETS[fmt_key]
        cover_html = f"""
        <section class="book-cover">
          <div class="cover-top">STANDARD ADVANCED TEXTBOOK SERIES · {html.escape(preset['label_ko'])}</div>
          <h1 class="cover-title">{html.escape(book_meta.get("title_ko", "토양 유기물학"))}</h1>
          <div class="cover-en">{html.escape(book_meta.get("title_en", ""))}</div>
          <div class="cover-rule"></div>
          <div class="cover-meta">
            <div><b>인쇄 판형:</b> {html.escape(preset['label_ko'])}</div>
            <div><b>대상 독자:</b> {html.escape(book_meta.get("target_audience", ""))}</div>
            <div><b>전체 구성:</b> 제1부 ~ 제5부 · 총 {len(chapters_content)}개 단원 · 과학 도해·정량 차트 {total_visuals}종</div>
            <div><b>근거 무결성:</b> 1차 공식기관·국내외 학회지·오픈교과서·C:\\SMC_GRAPHRAG 지식그래프 총 {len(cited_sources)}종 인용 검증 완료</div>
            <div><b>편찬일:</b> {datetime.now().strftime("%Y년 %m월 %d일")}</div>
          </div>
        </section>
        """
        hdr_label = f"토양 유기물학 · {preset['label_ko']}"
        full_html = (
            f'<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">'
            f'<style>{_book_trim_css(preset, hdr_label)}</style></head>'
            f'<body>{cover_html}{body_html_joined}</body></html>'
        )
        html_path = out_dir / preset["html_filename"]
        pdf_path = out_dir / preset["filename"]
        html_path.write_text(full_html, encoding="utf-8")
        pdf_ok = _render_html_to_pdf(full_html, pdf_path)
        pages = len(PdfReader(str(pdf_path)).pages) if pdf_ok and pdf_path.is_file() else 0
        for f in (html_path, pdf_path):
            if f.is_file():
                shutil.copy2(f, e_dir / f.name)
        editions_report[fmt_key] = {
            "label_ko": preset["label_ko"],
            "page_size": preset["page_size"],
            "status": "OK" if pdf_ok else "PDF_FAILED",
            "pdf_filename": pdf_path.name,
            "pdf_path": str(pdf_path),
            "pdf_pages": pages,
            "pdf_size_mb": round(pdf_path.stat().st_size / (1024 * 1024), 2) if pdf_path.is_file() else 0,
        }

    docx_path = out_dir / "Soil_Organic_Matter_Master_Book.docx"
    docx_figs = 0
    if build_docx:
        docx_figs = _build_master_docx(
            book_meta, parts_data, chapters_content, cited_sources, index_map, visuals_map, docx_path
        )
        if docx_path.is_file():
            shutil.copy2(docx_path, e_dir / docx_path.name)

    primary_pdf = editions_report.get("shinkuk") or editions_report.get("b5") or editions_report.get("a4") or {}
    report = {
        "status": "OK" if all(v["status"] == "OK" for v in editions_report.values()) else "PARTIAL_FAILED",
        "chapters_bound": len(chapters_content),
        "total_chars": sum(len(b) for _, b in chapters_content.values()),
        "total_visuals": total_visuals,
        "docx_embedded_figures": docx_figs,
        "cited_sources_total": len(cited_sources),
        "index_terms_total": len(index_map),
        "editions": editions_report,
        # 하위 호환 필드
        "pdf_path": primary_pdf.get("pdf_path", ""),
        "pdf_pages": primary_pdf.get("pdf_pages", 0),
        "pdf_size_mb": primary_pdf.get("pdf_size_mb", 0),
        "docx_path": str(docx_path),
        "docx_size_mb": round(docx_path.stat().st_size / (1024 * 1024), 2) if docx_path.is_file() else 0,
        "e_drive_mirror": str(e_dir),
    }
    (cfg.reports_dir / "master_book_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="《토양 유기물학》 16개 단원 출판 판형(신국판/B5/A4) 합본 제본기")
    parser.add_argument(
        "--format",
        default="all",
        choices=["shinkuk", "b5", "a4", "all"],
        help="출력 판형 선택 (shinkuk=152x225mm, b5=182x257mm, a4=210x297mm, all=3종 전체)",
    )
    parser.add_argument("--no-docx", action="store_true", help="Word DOCX 재생성 생략")
    parser.add_argument("--no-exercises", action="store_true", help="합본에서 연습문제(형성평가) 절을 빼고 제본")
    args = parser.parse_args()

    fmts = ["shinkuk", "b5", "a4"] if args.format == "all" else [args.format]
    rep = bind_master_book(formats=fmts, build_docx=not args.no_docx, include_exercises=not args.no_exercises)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep["status"] == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
