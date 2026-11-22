"""Phase 3: 4종 멀티포맷 자동 출판 파이프라인 (multi-format-publisher).

감사 PASS를 통과한 단일 마스터 원고(content/chapters/chNN.mdx)와
검증 근거 패킷(E:\\SMC_Report_Platform_Data\\evidence\\)에서 아래 4종 산출물을 동시 생성한다.

산출물 (content/exports/<chNN>/ 및 E:\\SMC_Report_Platform_Data\\exports\\<chNN>\\ 동시 저장):
1. 전문 교재 (Textbook): <chNN>_textbook.qmd + <chNN>_textbook.pdf
2. 교과서 단원본 (Curriculum): <chNN>_curriculum.mdx + <chNN>_curriculum.pdf
3. 심층 기술보고서 (Executive Report): <chNN>_report.md + <chNN>_report.docx + <chNN>_report.pdf
4. 인터랙티브 웹페이지 (Interactive Web): <chNN>_interactive.html (대시보드 /chapters/<chNN> 연동)

사용 예:
    .venv\\Scripts\\python.exe scripts\\build_outputs.py --chapters ch01,ch07,ch10,ch11
    .venv\\Scripts\\python.exe scripts\\build_outputs.py --all
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from markdown_it import MarkdownIt

from config import PlatformConfig, get_config
from figure_registry import figure_css, inject_figures_into_chapter_html, load_chapter_visuals
from math_typography import add_rich_runs_to_docx_paragraph, math_typography_css
from naver_blog_formatter import (
    apply_naver_inline_styles,
    generate_20_hashtags,
    render_hashtag_box_html,
    render_naver_figure_html,
    sanitize_math_for_naver_blog,
)
from verify_citations import verify_target


MD_PARSER = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable("table")

# 연습문제 관련 H2 절을 찾는 단어 (제목에 하나라도 있으면 그 절 전체를 뺀다)
EXERCISE_HEADING_KEYWORDS = ("연습문제", "형성평가", "Formative Assessment", "Exercises")


def strip_exercise_sections(body: str) -> str:
    """원고에서 '## …연습문제…' 같은 H2 절을 다음 H2(또는 H1) 직전까지 통째로 제거한다.

    프로젝트 옵션 enable_exercises=False 이거나 CLI --no-exercises 일 때 사용한다.
    문제↔풀이 앵커 링크(#chNN-qK, #chNN-aK)도 일반 글자로 바꿔 깨진 링크를 남기지 않는다.
    """
    out: list[str] = []
    skipping = False
    for ln in body.splitlines():
        if ln.startswith("## "):
            skipping = any(k in ln for k in EXERCISE_HEADING_KEYWORDS)
            if skipping:
                continue
        elif ln.startswith("# "):
            skipping = False
        if not skipping:
            out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"\[([^\]]*)\]\(#ch\d+-[qa]\d+\)", r"\1", text)
    return text + ("\n" if body.endswith("\n") else "")


def _find_chromium() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$", text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    return meta, m.group(2).strip()


def _load_all_sources_map(cfg: PlatformConfig) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not cfg.evidence_dir.is_dir():
        return out
    for p in sorted(cfg.evidence_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            for s in d.get("sources", []):
                sid = s.get("source_id")
                if sid:
                    out[sid] = s
        except Exception:
            continue
    return out


def _clean_mdx_artifacts(body: str) -> str:
    """MDX 원고 내 HTML 주석(<br>, NEED_EVIDENCE, 내부 마커 등)을 출판용으로 정리한다."""
    cleaned = re.sub(r"<!--\s*(?:NEED_EVIDENCE:.*?|EXPANDED_500P_V1|MYTH_VS_FACT_V1|QUIZ_LINKED_V1)\s*-->", "", body, flags=re.S | re.I)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.I)
    return cleaned.strip()


def _split_sections_by_h2(body: str) -> tuple[str, list[tuple[str, str]]]:
    """## 헤딩 기준으로 서두와 섹션 목록을 분리한다."""
    parts = re.split(r"(?m)^##\s+", body)
    preamble = parts[0].strip()
    sections: list[tuple[str, str]] = []
    for part in parts[1:]:
        lines = part.splitlines()
        heading = lines[0].strip() if lines else ""
        content = "\n".join(lines[1:]).strip()
        sections.append((heading, content))
    return preamble, sections


def _render_html_to_pdf(html_content: str, pdf_path: Path) -> bool:
    """Headless Chrome/Edge --print-to-pdf 로 한글 폰트 완벽 지원 A4 PDF를 생성한다."""
    browser = _find_chromium()
    if not browser:
        return False
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        html_file = Path(tmp) / "render.html"
        html_file.write_text(html_content, encoding="utf-8")
        cmd = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path.resolve()}",
            html_file.resolve().as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return proc.returncode == 0 and pdf_path.is_file() and pdf_path.stat().st_size > 1000


def _print_css(accent: str, header_label: str) -> str:
    return f"""
    @page {{
      size: A4;
      margin: 20mm 18mm 20mm 18mm;
      @top-right {{ content: "{header_label}"; font-size: 8.5pt; color: #64748b; }}
      @bottom-center {{ content: counter(page); font-size: 9pt; color: #475569; }}
    }}
    body {{
      font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
      font-size: 10.2pt;
      line-height: 1.72;
      color: #1e293b;
      margin: 0;
    }}
    .cover-banner {{
      background: linear-gradient(135deg, {accent} 0%, #0f172a 100%);
      color: #ffffff;
      padding: 20px 24px;
      border-radius: 10px;
      margin-bottom: 18px;
    }}
    .cover-banner .kicker {{ font-size: 9pt; letter-spacing: 0.8px; opacity: 0.85; text-transform: uppercase; }}
    .cover-banner h1 {{ margin: 6px 0 4px; font-size: 18pt; color: #ffffff; border: none; padding: 0; }}
    .cover-banner .meta {{ font-size: 9pt; opacity: 0.9; }}
    h1 {{ font-size: 16pt; color: #0f172a; border-bottom: 2px solid {accent}; padding-bottom: 6px; margin-top: 22px; }}
    h2 {{ font-size: 13pt; color: {accent}; border-left: 4px solid {accent}; padding-left: 10px; margin-top: 22px; page-break-after: avoid; }}
    h3 {{ font-size: 11pt; color: #0f172a; margin-top: 14px; page-break-after: avoid; }}
    h4 {{ font-size: 9.8pt; color: #047857; background: #ecfdf5; border-left: 3.5px solid #059669; padding: 4px 10px; margin: 10px 0 6px; border-radius: 0 6px 6px 0; page-break-after: avoid; }}
    blockquote, .callout {{
      background: #f8fafc;
      border-left: 4px solid {accent};
      padding: 10px 14px;
      margin: 12px 0;
      border-radius: 0 8px 8px 0;
    }}
    .exec-box {{
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-left: 5px solid {accent};
      padding: 14px 16px;
      border-radius: 8px;
      margin: 14px 0 18px;
    }}
    .activity-box {{
      background: #fefce8;
      border: 1px solid #fde047;
      border-left: 5px solid #ca8a04;
      padding: 12px 15px;
      border-radius: 8px;
      margin: 14px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0 16px;
      font-size: 8.8pt;
      page-break-inside: auto;
    }}
    th, td {{
      border: 1px solid #cbd5e1;
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    th {{ background: {accent}; color: #ffffff; font-weight: 700; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    code {{
      background: #f1f5f9;
      padding: 1px 4px;
      border-radius: 4px;
      font-family: Consolas, 'D2Coding', monospace;
      font-size: 9pt;
    }}
    pre {{
      background: #0f172a;
      color: #e2e8f0;
      padding: 10px 12px;
      border-radius: 8px;
      overflow-x: auto;
      font-size: 8.5pt;
    }}
    pre code {{ background: transparent; color: inherit; padding: 0; }}
    .cite-tag {{
      display: inline-block;
      font-size: 8pt;
      font-weight: 700;
      color: {accent};
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 4px;
      padding: 0 4px;
    }}
    {math_typography_css("print")}
    """


def _highlight_citations_html(rendered_html: str) -> str:
    return re.sub(
        r"\[(SRC-\d{2,4}(?:,\s*[^\]]+)?)\]",
        r'<span class="cite-tag">[\1]</span>',
        rendered_html,
    )


# ---------- 1. 전문 교재 (Textbook .qmd + PDF) ----------
def build_textbook(
    ch_id: str,
    meta: dict[str, Any],
    body: str,
    out_dir: Path,
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    title = meta.get("title", ch_id)
    book_title = str(meta.get("book_title") or "전문 교재")
    qmd_content = (
        "---\n"
        f'title: "{title}"\n'
        f'subtitle: "《{book_title}》 전문 교재판"\n'
        'lang: ko\n'
        "format:\n"
        "  pdf:\n"
        "    documentclass: scrreprt\n"
        "    toc: true\n"
        "    number-sections: true\n"
        "---\n\n"
        + body
        + "\n"
    )
    qmd_path = out_dir / f"{ch_id}_textbook.qmd"
    qmd_path.write_text(qmd_content, encoding="utf-8")

    clean_body = _clean_mdx_artifacts(body)
    body_html = _highlight_citations_html(MD_PARSER.render(clean_body))
    if visuals_map:
        body_html = inject_figures_into_chapter_html(ch_id, body_html, visuals_map, theme="print")
    full_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><style>{_print_css("#1d4ed8", f"{book_title} 전문 교재")}{figure_css("print")}</style></head>
<body>
  <div class="cover-banner">
    <div class="kicker">PROFESSIONAL TEXTBOOK · 전문 교재판</div>
    <h1>{html.escape(title)}</h1>
    <div class="meta">대상 독자: {html.escape(str(meta.get("audience", "대학 전공 심화 및 연구 실무자")))} &nbsp;|&nbsp; 근거 패킷: {html.escape(str(meta.get("evidence_packet", "")))}</div>
  </div>
  {body_html}
</body></html>"""

    pdf_path = out_dir / f"{ch_id}_textbook.pdf"
    pdf_ok = _render_html_to_pdf(full_html, pdf_path)
    return {"qmd": str(qmd_path), "pdf": str(pdf_path) if pdf_ok else ""}


# ---------- 2. 교과서 단원본 (Curriculum .mdx + PDF) ----------
def build_curriculum(
    ch_id: str,
    meta: dict[str, Any],
    body: str,
    out_dir: Path,
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    title = meta.get("title", ch_id)
    preamble, sections = _split_sections_by_h2(body)
    # 연습문제 절이 없는 원고(연습문제 끄기)면 탐구 활동·형성평가 문구도 넣지 않는다
    has_exercises = any(any(k in h for k in EXERCISE_HEADING_KEYWORDS) for h, _ in sections)

    # 성취기준 박스 + 탐구 활동 삽입 + 형성평가 라벨 재구성
    cur_parts = [
        "---",
        f'title: "{title} (교과서 단원본)"',
        'format_type: "curriculum_textbook"',
        "---",
        "",
        f"# {title}",
        "",
        ("> **[성취기준 및 학습 안내]** 본 단원을 학습한 후 학생은 핵심 개념의 원리를 도식과 사례로 설명하고, 제시된 탐구 활동과 형성평가 문항을 근거 기반으로 해결할 수 있다."
         if has_exercises else
         "> **[성취기준 및 학습 안내]** 본 단원을 학습한 후 학생은 핵심 개념의 원리를 도식과 사례로 설명하고, 현장 사례에 근거 기반으로 적용할 수 있다."),
        "",
    ]
    # 기존 preamble에서 학습 목표 보존
    for ln in preamble.splitlines():
        if ln.strip().startswith(">"):
            cur_parts.append(ln)
    cur_parts.append("")

    activity_inserted = False
    for heading, content in sections:
        if "연습문제" in heading:
            cur_parts.append("## 형성평가 (Formative Assessment)")
            cur_parts.append(content)
            cur_parts.append("")
        elif "참고문헌" in heading:
            cur_parts.append(f"## {heading}")
            cur_parts.append(content)
            cur_parts.append("")
        else:
            cur_parts.append(f"## {heading}")
            cur_parts.append(content)
            cur_parts.append("")
            if has_exercises and not activity_inserted and not heading.startswith("핵심 용어집"):
                cur_parts.append(
                    f"> **탐구 활동 (생각해 보기 — {heading})**: 본 절에서 학습한 핵심 메커니즘을 인근 농경지(논·밭·시설하우스) 사례에 적용해 보고, 유기물 관리 시 발생할 수 있는 장점과 트레이드오프를 3가지 이상 토의해 보시오."
                )
                cur_parts.append("")
                activity_inserted = True

    cur_mdx = "\n".join(cur_parts)
    mdx_path = out_dir / f"{ch_id}_curriculum.mdx"
    mdx_path.write_text(cur_mdx, encoding="utf-8")

    _, cur_body = _parse_frontmatter(cur_mdx)
    body_html = _highlight_citations_html(MD_PARSER.render(_clean_mdx_artifacts(cur_body)))
    if visuals_map:
        body_html = inject_figures_into_chapter_html(ch_id, body_html, visuals_map, theme="print")
    body_html = body_html.replace("<blockquote>\n<p><strong>탐구 활동", '<div class="activity-box"><p><strong>탐구 활동')
    body_html = re.sub(r"(<div class=\"activity-box\">[\s\S]*?)</blockquote>", r"\1</div>", body_html)

    book_title = str(meta.get("book_title") or "전문 교재")
    full_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><style>{_print_css("#047857", f"{book_title} 교과서 단원본")}{figure_css("print")}</style></head>
<body>
  <div class="cover-banner">
    <div class="kicker">CURRICULUM TEXTBOOK · 교과서 단원본</div>
    <h1>{html.escape(title)}</h1>
    <div class="meta">{"성취기준 · 탐구 활동 · 핵심 용어집 · 형성평가 포함" if has_exercises else "성취기준 · 핵심 용어집 포함 (연습문제 제외판)"}</div>
  </div>
  {body_html}
</body></html>"""

    pdf_path = out_dir / f"{ch_id}_curriculum.pdf"
    pdf_ok = _render_html_to_pdf(full_html, pdf_path)
    return {"mdx": str(mdx_path), "pdf": str(pdf_path) if pdf_ok else ""}


# ---------- 3. 심층 기술보고서 (Executive Report .md + .docx + .pdf) ----------
def _build_report_docx(
    title: str,
    exec_summary_lines: list[str],
    sections: list[tuple[str, str]],
    docx_path: Path,
    ch_visuals: list[dict[str, Any]] | None = None,
) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    # 기본 한글 폰트 설정 (맑은 고딕)
    style_normal = doc.styles["Normal"]
    style_normal.font.name = "Malgun Gothic"
    style_normal.font.size = Pt(10.5)
    style_normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

    # 표지/헤더 타이틀
    p_kicker = doc.add_paragraph()
    r_k = p_kicker.add_run("EXECUTIVE TECHNICAL REPORT · 심층 기술·정책 보고서")
    r_k.bold = True
    r_k.font.size = Pt(9)
    r_k.font.color.rgb = RGBColor(30, 64, 175)

    h0 = doc.add_heading(title, level=0)
    for run in h0.runs:
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

    # 1페이지 핵심 요약 (Executive Summary) 박스
    h_ex = doc.add_heading("핵심 요약 (Executive Summary)", level=1)
    for run in h_ex.runs:
        run.font.name = "Malgun Gothic"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")
    for line in exec_summary_lines:
        p = doc.add_paragraph(style="List Bullet")
        r = p.add_run(line)
        r.font.name = "Malgun Gothic"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

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
                    font_size=8.5,
                    color_rgb=(255, 255, 255) if r_idx == 0 else None,
                    base_bold=(r_idx == 0),
                )
                if r_idx == 0:
                    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="1E3A8A"/>')
                    cell._tc.get_or_add_tcPr().append(shading)

    vis_list = list(ch_visuals or [])
    body_sec_indices = [idx for idx, (h, _) in enumerate(sections) if "참고문헌" not in h] or list(range(len(sections)))
    vis_by_sec: dict[int, list[dict[str, Any]]] = {}
    if vis_list and body_sec_indices:
        for v_i, v_item in enumerate(vis_list):
            target_pos = body_sec_indices[min(len(body_sec_indices) - 1, (v_i * len(body_sec_indices)) // max(1, len(vis_list)))]
            vis_by_sec.setdefault(target_pos, []).append(v_item)

    for sec_i, (heading, content) in enumerate(sections):
        h = doc.add_heading(heading, level=1)
        for run in h.runs:
            run.font.name = "Malgun Gothic"
            run._element.rPr.rFonts.set(qn("w:eastAsia"), "Malgun Gothic")

        for v_item in vis_by_sec.get(sec_i, []):
            img_str = v_item.get("docx_image_path", "")
            if img_str and Path(img_str).is_file():
                p_img = doc.add_paragraph()
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.add_run().add_picture(img_str, width=Inches(5.5))
                fig_no = v_item.get("fig_no", "")
                title_ko = v_item.get("title_ko") or v_item.get("caption_ko", "")
                hdr = f"[{fig_no}] {title_ko}" if fig_no else title_ko
                p_cap = doc.add_paragraph()
                add_rich_runs_to_docx_paragraph(p_cap, hdr, font_size=9.2, base_bold=True, color_rgb=(15, 23, 42))
                if v_item.get("description_ko"):
                    p_desc = doc.add_paragraph()
                    add_rich_runs_to_docx_paragraph(p_desc, v_item["description_ko"], font_size=9.0, color_rgb=(51, 65, 85))

        clean_c = _clean_mdx_artifacts(content)
        lines = clean_c.splitlines()
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
            if ln.startswith("<a id=") or ln.startswith("*[↑ 문제"):
                i += 1
                continue
            if ln.startswith("### "):
                hh = doc.add_heading("", level=2)
                add_rich_runs_to_docx_paragraph(hh, ln[4:].strip(), font_size=11.5, base_bold=True, color_rgb=(30, 41, 59))
            elif ln.startswith("#### "):
                p_ans = doc.add_paragraph()
                p_ans._p.get_or_add_pPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="ECFDF5"/>'))
                add_rich_runs_to_docx_paragraph(p_ans, ln[5:].strip(), font_size=10.2, base_bold=True, color_rgb=(4, 120, 87))
            elif ln.startswith('<div class="math-block">'):
                p_eq = doc.add_paragraph()
                p_eq.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_eq._p.get_or_add_pPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="F1F5F9"/>'))
                add_rich_runs_to_docx_paragraph(p_eq, ln, font_size=10.0, color_rgb=(15, 23, 42))
            elif ln.startswith(("* ", "- ")):
                p = doc.add_paragraph(style="List Bullet")
                add_rich_runs_to_docx_paragraph(p, ln[2:].strip(), font_size=10.0)
            else:
                p = doc.add_paragraph()
                add_rich_runs_to_docx_paragraph(p, ln.lstrip("> ").strip(), font_size=10.0)
            i += 1

    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(docx_path))


def build_executive_report(
    ch_id: str,
    meta: dict[str, Any],
    body: str,
    out_dir: Path,
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    title = meta.get("title", ch_id)
    _, sections = _split_sections_by_h2(body)

    # 연습문제·학습활동 제거 (보고서 변환 규칙)
    report_sections = [
        (h, c)
        for h, c in sections
        if not any(skip in h for skip in ("연습문제", "형성평가", "탐구 활동"))
    ]

    cited_ids = sorted(set(re.findall(r"\[(SRC-\d{2,4})", body)))
    exec_lines = [
        f"보고서 주제: {title}",
        f"검증 근거 기반: 총 {len(cited_ids)}건의 1차 출처({', '.join(cited_ids[:10])}{' 외' if len(cited_ids) > 10 else ''})와 교차 대조 완료.",
    ]
    for h, c in report_sections:
        if "참고문헌" in h or "용어집" in h:
            continue
        first_para = next(
            (
                ln.strip()
                for ln in _clean_mdx_artifacts(c).splitlines()
                if ln.strip() and not ln.strip().startswith(("#", "|", "*", "-", ">"))
            ),
            "",
        )
        if first_para:
            exec_lines.append(f"[{h}] {first_para[:170]}{'...' if len(first_para) > 170 else ''}")

    md_parts = [
        f"# [심층 기술보고서] {title}",
        "",
        "## 핵심 요약 (Executive Summary)",
        "",
    ]
    for el in exec_lines:
        md_parts.append(f"- {el}")
    md_parts.append("")
    for h, c in report_sections:
        md_parts.append(f"## {h}")
        md_parts.append(c)
        md_parts.append("")

    report_md = "\n".join(md_parts)
    md_path = out_dir / f"{ch_id}_report.md"
    md_path.write_text(report_md, encoding="utf-8")

    docx_path = out_dir / f"{ch_id}_report.docx"
    _build_report_docx(title, exec_lines, report_sections, docx_path, ch_visuals=(visuals_map or {}).get(ch_id, []))

    body_html = _highlight_citations_html(MD_PARSER.render(_clean_mdx_artifacts(report_md)))
    if visuals_map:
        body_html = inject_figures_into_chapter_html(ch_id, body_html, visuals_map, theme="print")
    full_html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"><style>{_print_css("#0f172a", "심층 기술·정책 보고서")}{figure_css("print")}</style></head>
<body>
  <div class="cover-banner">
    <div class="kicker">EXECUTIVE TECHNICAL REPORT · 심층 기술·정책 보고서</div>
    <h1>{html.escape(title)}</h1>
    <div class="meta">검증 출처 {len(cited_ids)}건 기반 · 연습문제 제외 · 의사결정·연구 실무용</div>
  </div>
  {body_html}
</body></html>"""
    pdf_path = out_dir / f"{ch_id}_report.pdf"
    pdf_ok = _render_html_to_pdf(full_html, pdf_path)

    return {"md": str(md_path), "docx": str(docx_path), "pdf": str(pdf_path) if pdf_ok else ""}


# ---------- 4. 네이버 블로그 게재용 인터랙티브 웹페이지 (Naver SmartEditor ONE + 소단원별 해시태그 20개) ----------
def build_interactive_web(
    ch_id: str,
    meta: dict[str, Any],
    body: str,
    sources_map: dict[str, dict[str, Any]],
    out_dir: Path,
    visuals_map: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, str]:
    title = meta.get("title", ch_id)
    clean_body = _clean_mdx_artifacts(body)
    preamble, sections = _split_sections_by_h2(clean_body)
    ch_visuals = list((visuals_map or {}).get(ch_id, []))

    toc_items: list[tuple[str, str, str]] = []
    heading_counter = 0
    cited_sids: set[str] = set()

    def _replace_cite(m: re.Match[str]) -> str:
        inner = m.group(1)
        sid = inner.split(",")[0].strip()
        cited_sids.add(sid)
        return f'<button type="button" class="cite-btn" data-sid="{html.escape(sid)}" onclick="showCite(\'{html.escape(sid)}\')">[{html.escape(inner)}]</button>'

    def _add_h3_ids(fragment: str) -> str:
        def _repl(m: re.Match[str]) -> str:
            nonlocal heading_counter
            heading_counter += 1
            plain = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip())
            hid = f"sec-{heading_counter}"
            toc_items.append(("h3", hid, plain))
            return f'<h3 id="{hid}">{m.group(1)}</h3>'

        return re.sub(r"<h3>(.*?)</h3>", _repl, fragment)

    def _transform_quiz_details(fragment: str) -> str:
        # 1) 표준화된 '<h4>▶ 문제 N 정답 및 상세 풀이</h4> ...' 블록을 문제 바로 아래 연결된 풀이 카드로 감싼다.
        def _wrap_linked_ans(m: re.Match[str]) -> str:
            title_h4 = m.group(1).strip()
            inner = m.group(2).strip()
            return (
                '<details class="quiz-ans" open '
                'style="margin:10px 0 22px;padding:12px 16px;background:#f4fbf6;border:1px solid #bbf7d0;border-left:4px solid #03C75A;border-radius:0 8px 8px 0;">'
                f'<summary style="cursor:pointer;font-weight:800;color:#047857;font-size:15px;">{title_h4} (접기/펼치기)</summary>'
                f'<div class="quiz-body" style="margin-top:10px;padding-top:8px;border-top:1px dashed #bbf7d0;">{inner}</div>'
                "</details>"
            )

        res = re.sub(
            r"<h4[^>]*>(▶\s*문제\s*\d+\s*정답\s*및\s*상세\s*풀이)</h4>([\s\S]*?)(?=<p[^>]*><a id=|<h3\b|\Z)",
            _wrap_linked_ans,
            fragment,
        )
        if res != fragment:
            return res
        # 2) 폴백(구형 포맷)
        return re.sub(
            r"<p[^>]*><strong>정답(.*?)</p>\s*(<ul[^>]*>[\s\S]*?</ul>|<p[^>]*>[\s\S]*?</p>)?",
            lambda m: (
                '<details class="quiz-ans" open style="margin:12px 0;padding:10px 14px;background:#f8fafc;border:1px solid #d1d5db;border-radius:8px;">'
                '<summary style="cursor:pointer;font-weight:700;color:#03a84e;">정답 및 해설 보기</summary>'
                f'<div class="quiz-body" style="margin-top:8px;"><p style="margin:0 0 8px;font-size:15px;line-height:1.8;color:#222222;"><strong>정답{m.group(1)}</p>{m.group(2) or ""}</div></details>'
            ),
            fragment,
        )

    # 서두(제목 + 학습 목표) 렌더링
    preamble_raw = MD_PARSER.render(preamble)
    preamble_html = apply_naver_inline_styles(preamble_raw, full_naver_math=False)
    preamble_html = re.sub(
        r"<h1>(.*?)</h1>",
        r'<h1 style="font-size:24px;font-weight:800;color:#111111;line-height:1.45;margin:0 0 18px;padding-bottom:14px;border-bottom:2px solid #03C75A;">\1</h1>',
        preamble_html,
    )
    preamble_html_pure = sanitize_math_for_naver_blog(preamble_html)
    preamble_html_interactive = re.sub(r"\[(SRC-\d{2,4}(?:,\s*[^\]]+)?)\]", _replace_cite, preamble_html)

    section_cards_interactive: list[str] = []
    section_blocks_pure_naver: list[str] = [
        f'<div style="margin-bottom:28px;">{preamble_html_pure}</div>'
    ]
    total_hashtags_generated = 0
    # 본문 소단원(참고문헌·연습문제 제외)에 단원 시각화 전체(10종+)를 균등 분산 배정
    body_web_secs = [
        idx for idx, (h, _) in enumerate(sections, 1)
        if not any(sk in h for sk in ("참고문헌", "연습문제", "형성평가"))
    ] or list(range(1, len(sections) + 1))
    web_vis_by_sec: dict[int, list[dict[str, Any]]] = {}
    if ch_visuals and body_web_secs:
        for v_i, v_item in enumerate(ch_visuals):
            target_s = body_web_secs[min(len(body_web_secs) - 1, (v_i * len(body_web_secs)) // max(1, len(ch_visuals)))]
            web_vis_by_sec.setdefault(target_s, []).append(v_item)

    for sec_idx, (heading, content) in enumerate(sections, 1):
        heading_counter += 1
        h2_id = f"sec-{heading_counter}"
        plain_h2 = re.sub(r"<[^>]+>", "", heading).strip()
        toc_items.append(("h2", h2_id, plain_h2))

        sec_html = MD_PARSER.render(content)
        sec_html = _add_h3_ids(sec_html)
        sec_html = apply_naver_inline_styles(sec_html)
        sec_html = _transform_quiz_details(sec_html)

        # 배정된 모든 시각화(PNG <img> + 줄글 해설)를 소단원 본문 첫 문단 직후 삽입
        sec_vis_items = web_vis_by_sec.get(sec_idx, [])
        if sec_vis_items and "참고문헌" not in plain_h2:
            fig_chunks = [render_naver_figure_html(v) for v in sec_vis_items]
            fig_html = "\n".join(c for c in fig_chunks if c)
            if fig_html:
                first_p_end = re.search(r"</p>", sec_html)
                if first_p_end:
                    pos = first_p_end.end()
                    sec_html = sec_html[:pos] + "\n" + fig_html + "\n" + sec_html[pos:]
                else:
                    sec_html = fig_html + "\n" + sec_html

        # 참고문헌을 제외한 모든 소단원 말미에 관련 해시태그 20개 텍스트 블록 추가
        is_ref_sec = "참고문헌" in plain_h2
        tags_20: list[str] = []
        hashtag_html = ""
        if not is_ref_sec:
            tags_20 = generate_20_hashtags(ch_id, plain_h2, content)
            total_hashtags_generated += len(tags_20)
            hashtag_html = render_hashtag_box_html(tags_20, sec_idx)

        h2_tag = (
            f'<h2 id="{h2_id}" style="font-size:20px;font-weight:800;color:#111111;line-height:1.45;'
            f'margin:8px 0 16px;padding:6px 0 6px 14px;border-left:5px solid #03C75A;background:#f9fdfb;">'
            f"{heading}</h2>"
        )

        # 순수 네이버 블로그 전용 HTML (버튼·CSS분수·sub/sup 깨짐 없이 그대로 Ctrl+A/C/V)
        pure_h2 = sanitize_math_for_naver_blog(h2_tag)
        pure_sec = sanitize_math_for_naver_blog(sec_html)
        # 네이버 스마트에디터는 <div class="table-wrap"> 래퍼 없이 직접 <table>을 붙여넣을 때 표 인식이 가장 안정적
        pure_sec = re.sub(r'<div class="table-wrap"[^>]*>\s*(<table[\s\S]*?</table>)\s*</div>', r"\1", pure_sec)
        pure_inner = f"{pure_h2}\n{pure_sec}\n{hashtag_html}"
        section_blocks_pure_naver.append(
            f'<section style="margin:0 0 36px;padding-bottom:28px;border-bottom:1px solid #e5e7eb;">{pure_inner}</section>'
        )

        # 인터랙티브 버전 (인용 클릭 버튼 + 소단원 상단 복사 툴바; 복사 시 툴바 제외 및 cite-btn 평문화)
        sec_html_interactive = re.sub(r"\[(SRC-\d{2,4}(?:,\s*[^\]]+)?)\]", _replace_cite, sec_html)
        copy_bar = (
            f'<div class="nb-sec-toolbar" data-no-copy="1">'
            f'<span class="nb-sec-num">소단원 {sec_idx}</span>'
            f'<div class="nb-sec-btns">'
            f'<button type="button" class="nb-btn nb-btn-green" onclick="copySectionForNaver(\'nb-copy-{sec_idx}\')">네이버 블로그 서식 복사</button>'
            + (
                f'<button type="button" class="nb-btn nb-btn-outline" onclick="copyHashtagsOnly(\'nb-copy-{sec_idx}\')">해시태그 20개 복사</button>'
                if tags_20
                else ""
            )
            + "</div></div>"
        )
        section_cards_interactive.append(
            f'<article class="nb-section-card">'
            f"{copy_bar}"
            f'<div class="nb-copy-area" id="nb-copy-{sec_idx}">'
            f"{h2_tag}\n{sec_html_interactive}\n{hashtag_html}"
            f"</div></article>"
        )

    # 본문에 인용된 출처만 경량 JSON으로 내장 (사이드 근거 패널용)
    embedded_sources: dict[str, dict[str, Any]] = {}
    for sid in sorted(cited_sids):
        src = sources_map.get(sid)
        if not src:
            continue
        excerpt = ""
        if src.get("chunks"):
            excerpt = str(src["chunks"][0].get("text", ""))[:420]
        embedded_sources[sid] = {
            "source_id": sid,
            "title": src.get("title", ""),
            "source_type": src.get("source_type", ""),
            "url": src.get("url", ""),
            "license_note": src.get("license_note", ""),
            "accessed_at": str(src.get("accessed_at", ""))[:10],
            "excerpt": excerpt,
        }

    toc_html = "\n".join(
        f'<a class="toc-{t}" href="#{hid}">{html.escape(lbl)}</a>'
        for t, hid, lbl in toc_items
    )

    # 1) 순수 네이버 블로그 게재용 HTML (chNN_naver_blog.html — 크롬 없이 바로 전체복사 가능)
    pure_naver_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)} — 네이버 블로그 바로 게재용</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; padding:24px 16px 60px; background:#ffffff; color:#222222; font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif; }}
    .naver-canvas {{ max-width:800px; margin:0 auto; background:#ffffff; }}
  </style>
</head>
<body>
  <div class="naver-canvas">
    {"".join(section_blocks_pure_naver)}
  </div>
</body>
</html>"""
    naver_only_path = out_dir / f"{ch_id}_naver_blog.html"
    naver_only_path.write_text(pure_naver_html, encoding="utf-8")

    # 2) 네이버 블로그 양식 인터랙티브 웹페이지 (chNN_interactive.html — 소단원별 원클릭 복사 + 출처 인스펙터)
    page_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{html.escape(title)} — 네이버 블로그 게재용 웹 교재</title>
  <style>
    :root {{ --bg:#f4f6f8; --paper:#ffffff; --border:#e5e7eb; --text:#222222; --muted:#6b7280; --naver:#03C75A; --naver-dark:#029f48; --accent:#1d4ed8; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif; background:var(--bg); color:var(--text); line-height:1.85; overflow-x:hidden; }}
    .topbar {{ position:sticky; top:0; z-index:40; background:#ffffff; border-bottom:2px solid var(--naver); padding:10px 20px; display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; box-shadow:0 2px 8px rgba(0,0,0,0.04); }}
    .topbar .title-wrap {{ display:flex; align-items:center; gap:8px; min-width:0; }}
    .naver-badge {{ background:var(--naver); color:#ffffff; font-size:11px; font-weight:800; padding:3px 8px; border-radius:6px; white-space:nowrap; }}
    .topbar h1 {{ margin:0; font-size:15.5px; color:#111827; }}
    .topbar .actions {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    .topbar input {{ background:#f9fafb; color:var(--text); border:1px solid #d1d5db; border-radius:8px; padding:6px 10px; font-size:13px; width:190px; }}
    .topbar a.btn, .topbar button.btn {{ background:var(--naver); color:#fff; border:none; text-decoration:none; padding:6px 12px; border-radius:8px; font-size:12.5px; font-weight:700; cursor:pointer; }}
    .topbar a.btn-sec {{ background:#f3f4f6; color:#374151; border:1px solid #d1d5db; }}
    .layout {{ display:grid; grid-template-columns:230px minmax(0, 820px) 290px; justify-content:center; gap:18px; max-width:1420px; margin:0 auto; padding:18px 14px 48px; }}
    .sidebar, .cite-drawer {{ position:sticky; top:68px; max-height:calc(100vh - 86px); overflow-y:auto; background:var(--paper); border:1px solid var(--border); border-radius:12px; padding:14px; }}
    .sidebar h3, .cite-drawer h3 {{ margin:0 0 10px; font-size:13.5px; color:var(--naver-dark); border-bottom:1px solid var(--border); padding-bottom:6px; }}
    .sidebar a {{ display:block; color:#374151; text-decoration:none; font-size:12.5px; padding:5px 8px; border-radius:6px; margin-bottom:2px; line-height:1.45; }}
    .sidebar a:hover {{ background:#eef7f1; color:#0b6b3a; }}
    .sidebar a.toc-h3 {{ padding-left:16px; font-size:11.8px; color:var(--muted); }}
    main.article {{ background:var(--paper); border:1px solid var(--border); border-radius:14px; padding:28px 34px; min-width:0; box-shadow:0 4px 18px rgba(0,0,0,0.03); }}
    main.article p, main.article li {{ overflow-wrap:anywhere; word-break:keep-all; }}
    main.article svg {{ max-width:100%; height:auto !important; display:block; }}
    .nb-guide-banner {{ background:#f4fbf6; border:1px solid #bbf7d0; border-radius:10px; padding:10px 14px; margin-bottom:20px; font-size:13px; color:#166534; display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; }}
    .nb-section-card {{ margin-bottom:28px; padding-bottom:22px; border-bottom:2px solid #f1f5f9; }}
    .nb-sec-toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:7px 12px; margin-bottom:14px; }}
    .nb-sec-num {{ font-size:12px; font-weight:800; color:#475569; }}
    .nb-sec-btns {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .nb-btn {{ border-radius:6px; padding:5px 10px; font-size:12px; font-weight:700; cursor:pointer; border:none; }}
    .nb-btn-green {{ background:var(--naver); color:#ffffff; }}
    .nb-btn-green:hover {{ background:var(--naver-dark); }}
    .nb-btn-outline {{ background:#ffffff; color:#03a84e; border:1px solid #86efac; }}
    .nb-btn-outline:hover {{ background:#eef7f1; }}
    .cite-btn {{ background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; border-radius:4px; padding:0 5px; font-size:12px; font-weight:700; cursor:pointer; margin:0 1px; }}
    .cite-btn:hover {{ background:#1d4ed8; color:#ffffff; }}
    .cite-card {{ font-size:12.5px; color:#374151; line-height:1.6; }}
    .cite-card .ctitle {{ font-weight:700; color:#111827; font-size:13.5px; margin-bottom:6px; }}
    .cite-card .cexcerpt {{ background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px; margin-top:8px; white-space:pre-wrap; font-size:12px; color:#4b5563; }}
    .toast {{ position:fixed; bottom:20px; right:20px; background:#111827; color:#ffffff; padding:10px 16px; border-radius:10px; font-size:13px; font-weight:600; display:none; z-index:999; box-shadow:0 8px 24px rgba(0,0,0,0.2); }}
    sub, sup {{ font-size:74%; line-height:0; position:relative; vertical-align:baseline; }}
    sup {{ top:-0.45em; }}
    sub {{ bottom:-0.22em; }}
    .m-frac {{ display:inline-flex; flex-direction:column; align-items:center; vertical-align:middle; margin:0 3px; font-size:90%; line-height:1.2; }}
    .m-frac .m-num {{ border-bottom:1px solid currentColor; padding:0 4px 1px; }}
    .m-frac .m-den {{ padding:1px 4px 0; }}
    .m-rxn {{ display:inline-flex; flex-direction:column; align-items:center; vertical-align:middle; margin:0 3px; line-height:1.05; }}
    .m-rxn .m-rxn-lbl {{ font-size:72%; }}
    @media (max-width: 1120px) {{
      .layout {{ grid-template-columns:minmax(0, 1fr); padding:10px; }}
      .sidebar, .cite-drawer {{ position:static; max-height:none; }}
      main.article {{ padding:16px 14px; }}
      .topbar input {{ width:100%; }}
    }}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="title-wrap">
      <span class="naver-badge">NAVER BLOG READY</span>
      <h1>{html.escape(title)}</h1>
    </div>
    <div class="actions">
      <input id="searchBox" type="search" placeholder="본문 키워드 검색..." oninput="filterSearch(this.value)" />
      <button type="button" class="btn" onclick="copyWholeChapterForNaver()">단원 전체 블로그 복사</button>
      <a class="btn btn-sec" href="/blog/{html.escape(ch_id)}" target="_blank">순수 블로그 HTML</a>
      <a class="btn btn-sec" href="/">← 대시보드</a>
    </div>
  </div>
  <div class="layout">
    <aside class="sidebar">
      <h3>소단원 목차 (TOC)</h3>
      {toc_html}
    </aside>
    <main class="article" id="articleBody">
      <div class="nb-guide-banner" data-no-copy="1">
        <span><b>네이버 블로그 바로 게재 안내:</b> 각 소단원 상단의 <b>[네이버 블로그 서식 복사]</b> 버튼을 누른 뒤 네이버 스마트에디터 ONE 본문에 <code>Ctrl+V</code>로 붙여넣으세요. 각 소단원 말미에 <b>관련 해시태그 20개</b>가 자동 포함되어 있습니다.</span>
      </div>
      <div id="nbPreamble">{preamble_html_interactive}</div>
      {"".join(section_cards_interactive)}
    </main>
    <aside class="cite-drawer">
      <h3>출처 근거 인스펙터 ([SRC-NN])</h3>
      <div id="citeCard" class="cite-card">
        본문의 <span class="cite-btn">[SRC-NN]</span> 배지를 클릭하면 원천 출처 메타데이터와 검증 발췌문이 여기에 표시됩니다. (네이버 블로그 복사 시에는 깔끔한 일반 텍스트 <code>[SRC-NN]</code>으로 자동 변환됩니다.)
      </div>
    </aside>
  </div>
  <div class="toast" id="toast"></div>
  <script>
    const SOURCES = {json.dumps(embedded_sources, ensure_ascii=False)};
    function esc(s) {{ return String(s||'').replace(/[&<>"']/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m])); }}
    function showToast(msg) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      setTimeout(() => {{ t.style.display = 'none'; }}, 3200);
    }}
    function showCite(sid) {{
      const s = SOURCES[sid];
      const box = document.getElementById('citeCard');
      if (!s) {{ box.innerHTML = '출처 정보를 찾을 수 없습니다: ' + esc(sid); return; }}
      box.innerHTML = `
        <div class="ctitle">[${{esc(s.source_id)}}] ${{esc(s.title)}}</div>
        <div><b>유형:</b> ${{esc(s.source_type)}} · <b>접근일:</b> ${{esc(s.accessed_at)}}</div>
        <div style="margin:4px 0;"><b>출처:</b> <a href="${{esc(s.url)}}" target="_blank" style="color:#03a84e; word-break:break-all;">${{esc(s.url)}}</a></div>
        <div><b>라이선스:</b> ${{esc(s.license_note)}}</div>
        <div class="cexcerpt">${{esc(s.excerpt || '(근거 패킷 원문 참조)')}}</div>
      `;
    }}
    const _SUB_UNI = {{'0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇','8':'₈','9':'₉','+':'₊','-':'₋','−':'₋'}};
    const _SUP_UNI = {{'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷','8':'⁸','9':'⁹','+':'⁺','-':'⁻','−':'⁻','=':'⁼','(':'⁽',')':'⁾','n':'ⁿ'}};
    function toNaverSub(txt) {{
      const t = (txt || '').trim();
      if (!t) return '';
      if ([...t].every(c => _SUB_UNI[c])) return [...t].map(c => _SUB_UNI[c]).join('');
      return /[ ,+\\-−\\/]/.test(t) ? '_(' + t + ')' : '_' + t;
    }}
    function toNaverSup(txt) {{
      const t = (txt || '').trim();
      if (!t) return '';
      if ([...t].every(c => _SUP_UNI[c])) return [...t].map(c => _SUP_UNI[c]).join('');
      return '^(' + t + ')';
    }}
    function flattenMathForNaverDom(root) {{
      // 1) 모든 sub/sup 먼저 변환 (분수·화살표 내부 첨자까지 보존)
      root.querySelectorAll('sub').forEach(el => {{
        el.replaceWith(document.createTextNode(toNaverSub(el.textContent)));
      }});
      root.querySelectorAll('sup').forEach(el => {{
        el.replaceWith(document.createTextNode(toNaverSup(el.textContent)));
      }});
      // 2) 세로 분수(.m-frac) → (분자) / (분모) 평탄화
      root.querySelectorAll('.m-frac').forEach(fr => {{
        const num = (fr.querySelector('.m-num')?.textContent || '').trim();
        const den = (fr.querySelector('.m-den')?.textContent || '').trim();
        const nStr = (num.length <= 10 && !/ [+\\-−×\\/] /.test(num)) ? num : '(' + num + ')';
        const dStr = (den.length <= 10 && !/ [+\\-−×\\/] /.test(den)) ? den : '(' + den + ')';
        fr.replaceWith(document.createTextNode(nStr + ' / ' + dStr));
      }});
      // 3) 반응 화살표(.m-rxn) → —[조건]→
      root.querySelectorAll('.m-rxn').forEach(rx => {{
        const lbl = (rx.querySelector('.m-rxn-lbl')?.textContent || '').trim();
        rx.replaceWith(document.createTextNode('—[' + lbl + ']→'));
      }});
      // 4) 표 래퍼(.table-wrap) 언랩 → 네이버 스마트에디터가 <table>을 표 객체로 직접 인식
      root.querySelectorAll('div.table-wrap').forEach(wrap => {{
        const tbl = wrap.querySelector('table');
        if (tbl) wrap.replaceWith(tbl);
      }});
    }}
    function buildCleanNaverHtml(el) {{
      const clone = el.cloneNode(true);
      clone.querySelectorAll('[data-no-copy="1"]').forEach(n => n.remove());
      clone.querySelectorAll('button.cite-btn').forEach(btn => {{
        const span = document.createElement('span');
        span.textContent = btn.textContent;
        span.style.color = '#2563eb';
        span.style.fontSize = '13px';
        btn.replaceWith(span);
      }});
      flattenMathForNaverDom(clone);
      return {{ html: clone.innerHTML, text: clone.innerText }};
    }}
    async function writeRichClipboard(htmlStr, textStr, okMsg) {{
      try {{
        if (navigator.clipboard && window.ClipboardItem) {{
          await navigator.clipboard.write([
            new ClipboardItem({{
              'text/html': new Blob([htmlStr], {{ type: 'text/html' }}),
              'text/plain': new Blob([textStr], {{ type: 'text/plain' }})
            }})
          ]);
          showToast(okMsg);
          return;
        }}
      }} catch (e) {{}}
      const tmp = document.createElement('div');
      tmp.style.position = 'fixed';
      tmp.style.left = '-9999px';
      tmp.style.background = '#ffffff';
      tmp.innerHTML = htmlStr;
      document.body.appendChild(tmp);
      const range = document.createRange();
      range.selectNodeContents(tmp);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      document.execCommand('copy');
      sel.removeAllRanges();
      tmp.remove();
      showToast(okMsg);
    }}
    function copySectionForNaver(id) {{
      const el = document.getElementById(id);
      if (!el) return;
      const clean = buildCleanNaverHtml(el);
      writeRichClipboard(clean.html, clean.text, '네이버 블로그 서식·이미지·해시태그 20개가 복사되었습니다! 에디터에 Ctrl+V 하세요.');
    }}
    function copyHashtagsOnly(id) {{
      const el = document.getElementById(id);
      if (!el) return;
      const tagEl = el.querySelector('.nb-hashtag-text');
      if (!tagEl) return;
      const txt = tagEl.innerText.trim();
      navigator.clipboard?.writeText(txt).then(() => showToast('관련 해시태그 20개가 복사되었습니다!')).catch(() => {{
        const ta = document.createElement('textarea');
        ta.value = txt;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        showToast('관련 해시태그 20개가 복사되었습니다!');
      }});
    }}
    function copyWholeChapterForNaver() {{
      const pre = document.getElementById('nbPreamble');
      const areas = Array.from(document.querySelectorAll('.nb-copy-area'));
      let combinedHtml = pre ? buildCleanNaverHtml(pre).html : '';
      let combinedText = pre ? buildCleanNaverHtml(pre).text + '\\n\\n' : '';
      areas.forEach(a => {{
        const c = buildCleanNaverHtml(a);
        combinedHtml += '<hr style="border:none;border-top:1px solid #e5e7eb;margin:28px 0;"/>' + c.html;
        combinedText += '\\n' + c.text + '\\n';
      }});
      writeRichClipboard(combinedHtml, combinedText, '단원 전체(소단원별 해시태그 20개 포함)가 네이버 블로그 서식으로 복사되었습니다!');
    }}
    document.querySelectorAll('table.sortable-table').forEach(tbl => {{
      const ths = tbl.querySelectorAll('thead th');
      ths.forEach((th, idx) => {{
        let asc = true;
        th.title = '클릭하여 정렬';
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {{
          const tbody = tbl.querySelector('tbody');
          if (!tbody) return;
          const rows = Array.from(tbody.querySelectorAll('tr'));
          rows.sort((a, b) => {{
            const av = (a.children[idx]?.textContent || '').trim();
            const bv = (b.children[idx]?.textContent || '').trim();
            return asc ? av.localeCompare(bv, 'ko', {{numeric:true}}) : bv.localeCompare(av, 'ko', {{numeric:true}});
          }});
          asc = !asc;
          rows.forEach(r => tbody.appendChild(r));
        }});
      }});
    }});
    function filterSearch(q) {{
      const paras = document.querySelectorAll('#articleBody p, #articleBody li');
      const kw = q.trim().toLowerCase();
      paras.forEach(el => {{
        el.style.outline = (kw && el.textContent.toLowerCase().includes(kw)) ? '2px solid #03C75A' : 'none';
      }});
    }}
  </script>
</body>
</html>"""

    html_path = out_dir / f"{ch_id}_interactive.html"
    html_path.write_text(page_html, encoding="utf-8")
    return {
        "html": str(html_path),
        "naver_blog_html": str(naver_only_path),
        "embedded_citations": str(len(embedded_sources)),
        "subsections_with_20_hashtags": str(total_hashtags_generated // 20),
    }


def build_chapter_outputs(ch_id: str, cfg: PlatformConfig | None = None, include_exercises: bool = True) -> dict[str, Any]:
    cfg = cfg or get_config()
    mdx_path = cfg.chapters_dir / f"{ch_id}.mdx"
    if not mdx_path.is_file():
        raise FileNotFoundError(f"Chapter not found: {mdx_path}")

    # 감사 PASS 사전 게이트 확인
    audit_pre = verify_target(mdx_path, cfg=cfg)
    if audit_pre["status"] != "PASS":
        return {"chapter_id": ch_id, "status": "BLOCKED_BY_AUDIT", "audit": audit_pre}

    raw_text = mdx_path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw_text)
    if not include_exercises:
        body = strip_exercise_sections(body)
    sources_map = _load_all_sources_map(cfg)

    out_dir = cfg.workspace_exports_dir / ch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    visuals_map = load_chapter_visuals(cfg)

    r_textbook = build_textbook(ch_id, meta, body, out_dir, visuals_map=visuals_map)
    r_curriculum = build_curriculum(ch_id, meta, body, out_dir, visuals_map=visuals_map)
    r_report = build_executive_report(ch_id, meta, body, out_dir, visuals_map=visuals_map)
    r_web = build_interactive_web(ch_id, meta, body, sources_map, out_dir, visuals_map=visuals_map)

    # 변환 산출물(.qmd, .mdx, .md) 인용 무결성 재검증
    post_audit = verify_target(out_dir, cfg=cfg)

    # E:\SMC_Report_Platform_Data\exports\<chNN>\ 미러 보관
    e_mirror = cfg.exports_dir / ch_id
    e_mirror.mkdir(parents=True, exist_ok=True)
    for f in out_dir.iterdir():
        if f.is_file():
            shutil.copy2(f, e_mirror / f.name)

    return {
        "chapter_id": ch_id,
        "status": "PASS" if post_audit["status"] == "PASS" else "AUDIT_FAIL",
        "export_dir": str(out_dir),
        "e_drive_mirror": str(e_mirror),
        "formats": {
            "textbook": r_textbook,
            "curriculum": r_curriculum,
            "report": r_report,
            "interactive_web": r_web,
        },
        "post_build_citation_audit": {
            "status": post_audit["status"],
            "checked_files": post_audit["checked_files"],
            "critical_errors": len(post_audit["critical_errors"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="4종 멀티포맷 자동 출판 파이프라인 (교재·교과서·보고서·인터랙티브 웹)")
    parser.add_argument("--chapters", default="", help="쉼표 구분 단원 ID (예: ch01,ch07,ch10,ch11)")
    parser.add_argument("--all", action="store_true", help="content/chapters/ 의 모든 .mdx 단원 빌드")
    parser.add_argument("--no-exercises", action="store_true", help="모든 산출물에서 연습문제(형성평가) 절을 빼고 빌드")
    args = parser.parse_args()

    cfg = get_config()
    if args.all:
        ch_ids = sorted(p.stem for p in cfg.chapters_dir.glob("*.mdx"))
    else:
        ch_ids = [c.strip() for c in args.chapters.split(",") if c.strip()]
    if not ch_ids:
        print("No chapters specified. Use --chapters ch01,ch07 or --all")
        return 1

    results = [build_chapter_outputs(cid, cfg=cfg, include_exercises=not args.no_exercises) for cid in ch_ids]
    report_path = cfg.reports_dir / "phase3_build_report.json"
    report_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"built": len(results), "report_path": str(report_path), "results": results}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] == "PASS" for r in results) else 2


if __name__ == "__main__":
    sys.exit(main())
